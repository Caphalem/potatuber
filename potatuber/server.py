"""The potato's nervous system: connects the Python organs to her faces.

Plural faces! Any number of pages can connect to the WebSocket at once:
the mascot window, the console, a subtitle overlay... Every event is
broadcast to all of them, and input can come from any of them (or from
the ears, which live here in Python-land).
"""

import asyncio
import base64
from contextlib import asynccontextmanager
import json
from pathlib import Path
import threading
import time

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from openai import APIConnectionError

from potatuber import vendor
from potatuber.brain import Brain
from potatuber.config import load
from potatuber.ears import Ears
from potatuber.events import AudioChunk, EyesState, History, NowSaying, SetExpression, SetToggle, SpeakEnd, SpeakStart, State, Tools, YouSaid
from potatuber.vts import VTS
from potatuber.eyes import Eyes
from potatuber.hands import make_default_hands
from potatuber.voice import Voice, make_speakable


EXP_SUFFIX = ".exp3.json"

config = load()

print(f"🥔 Waking up {config.character.name}...")

print("   Checking frontend libraries...")
vendor.ensure()

t = time.perf_counter()
print("   Loading voice (Pocket TTS)...")
voice = Voice(config.voice.sample, config.voice.pitch_shift, config.voice.language)
print(f"   ...voice ready in {time.perf_counter() - t:.1f}s")

print("   Connecting brain...") # This one's instant — it's just an HTTP client.
brain = Brain(
    base_url=config.brain.base_url,
    model=config.brain.model,
    system_prompt=config.character.system_prompt,
    max_history=config.brain.max_history,
    reminder=config.character.reminder
)

t = time.perf_counter()
print("   Loading ears (Whisper)...")
ears = Ears(config.ears.whisper_model, config.ears.hotkey, config.ears.prompt)
print(f"   ...ears ready in {time.perf_counter() - t:.1f}s")

if config.eyes.enabled:
    eyes = Eyes(config.eyes.max_width)
    print("   Eyes ready")
else:
    eyes = None

vts = (
    VTS(config.vts, toggles=config.face.toggles, form_range=config.face.mouth_form_range)
    if config.vts.enabled else None
)

print("🥔 All organs ready!")

clients: set[WebSocket] = set()

# One conversation at a time: if the ears and the console both submit,
# the second one politely waits its turn instead of interleaving.
conversation_lock = asyncio.Lock()

eyes_on = {"value": False}  # always boots OFF — vision is expensive
current_state = {"value": "idle"}

def eyes_state() -> EyesState:
    return EyesState(available=eyes is not None, enabled=eyes_on["value"])


def history() -> History:
    """What she remembers — which, thanks to max_history, is also exactly
    what the console should show. Older exchanges she's forgotten don't
    appear, and that's the truth about her memory.

    Tool uses are rebuilt too: each assistant message's tool_calls get
    paired with their results by tool_call_id, in the order they happened."""
    results = {m["tool_call_id"]: m["content"]
               for m in brain.messages if m["role"] == "tool"}
    entries = []
    for m in brain.messages[1:]:  # skip the system prompt
        if m["role"] == "user":
            entries.append({"role": "user", "text": m["content"]})
        elif m["role"] == "assistant":
            if m.get("content"):
                entries.append({"role": "assistant", "text": m["content"]})
            for call in m.get("tool_calls", []):
                fn = call["function"]
                try:
                    args = json.loads(fn["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = fn["arguments"]  # broken JSON — show it raw
                entries.append({
                    "role": "tool",
                    "name": fn["name"],
                    "args": args,
                    "result": results.get(call["id"], ""),
                })
    return History(messages=entries)


def tools_state() -> Tools:
    schemas = brain.hands.schemas if brain.hands else []
    return Tools(tools=[
        {"name": s["function"]["name"], "description": s["function"]["description"]}
        for s in schemas
    ])


def scan_expressions(model_path: str) -> list[dict]:
    """Find every expression in the model folder, however it's nested.

    Normally pixi-live2d-display only knows about expressions listed in the
    model3.json "Expressions" array — but VTube Studio ignores that array and
    scans the folder instead, so riggers who only test in VTS routinely leave
    it empty. We do what VTS does: scan, and name each expression after its
    file. The frontend then injects this list into the settings before the
    library sees them, so the array in the file no longer matters.
    """
    model_dir = Path("frontend") / Path(model_path).parent
    return [
        {"Name": p.name[:-len(EXP_SUFFIX)], "File": p.relative_to(model_dir).as_posix()}
        for p in sorted(model_dir.rglob(f"*{EXP_SUFFIX}"))
    ]


async def learn_expressions(expressions: list[str]) -> None:
    """Give her tools for whatever body she's wearing: faces AND outfits."""
    toggles = [e for e in expressions if e in config.face.toggles]
    emotions = [e for e in expressions if e not in config.face.toggles]
    if "Neutral" not in emotions:
        emotions.append("Neutral")
    brain.hands = make_default_hands(emotions, toggles)

    note = (f"You can change your look with the set_expression tool. "
            f"Your available faces: {', '.join(emotions)}. Use them to react!")
    if toggles:
        note += (f" You also have outfit pieces: {', '.join(toggles)}. Use set_toggle "
                 f"to put them on or take them off — they stay until you change them.")
    brain.add_instructions(note)

    await broadcast(tools_state())

    print(f"🥔 Learned faces: {', '.join(emotions)}"
          + (f" | outfits: {', '.join(toggles)}" if toggles else ""))


async def set_state(state: str) -> None:
    current_state["value"] = state
    await broadcast(State(state=state))


async def broadcast(event) -> None:
    """Send one event to every connected page. Dead pages get dropped."""
    for ws in list(clients):
        try:
            await ws.send_text(event.model_dump_json())
        except Exception:
            clients.discard(ws)


async def send_audio(audio: np.ndarray) -> None:
    await broadcast(AudioChunk(
        data=base64.b64encode(audio.tobytes()).decode(),
        sample_rate=voice.sample_rate,
    ))


async def speak(text: str) -> None:
    await broadcast(SpeakStart(text=text))

    speakable = make_speakable(text)
    if not speakable:
        await broadcast(SpeakEnd())
        return

    chunks = voice.say(speakable)

    if vts:
        # VTube Studio is her body: Python plays the audio itself and streams
        # the volume in as MouthOpen. That also makes US the timing authority,
        # so the subtitle relay fires from here instead of from the browser.
        audio = np.concatenate(await asyncio.to_thread(list, chunks))
        await broadcast(NowSaying(text=text))
        await asyncio.to_thread(vts.play, audio, voice.sample_rate)
        await broadcast(NowSaying(text=""))
    elif config.voice.stream_audio:
        while (chunk := await asyncio.to_thread(next, chunks, None)) is not None:
            await send_audio(chunk)
    else:
        all_chunks = await asyncio.to_thread(list, chunks)
        await send_audio(np.concatenate(all_chunks))

    await broadcast(SpeakEnd())


async def respond(user_text: str, image: str | None) -> None:
    await set_state("thinking")
    speaking = False

    try:
        items = brain.think(user_text, image)
        while (item := await asyncio.to_thread(next, items, None)) is not None:
            kind, payload = item
            if kind == "event":
                if vts and isinstance(payload, SetExpression):
                    await vts.set_expression(payload.name)
                elif vts and isinstance(payload, SetToggle):
                    await vts.set_toggle(payload.name, payload.on)
                else:
                    await broadcast(payload)
            else:
                if not speaking:
                    # The first sentence just finished generating — NOW she's
                    # speaking. Everything before this was genuinely thinking.
                    await set_state("speaking")
                    speaking = True
                await speak(payload)
    except APIConnectionError:
        print("🥔 Can't reach the brain! Is LM Studio running, with the "
              f"server on, at {config.brain.base_url}?")
        await speak("I can't reach my brain right now...")

    await set_state("idle")


async def handle_user_text(text: str) -> None:
    """The one entrance for ALL input — ears, console, whatever comes later."""
    async with conversation_lock:
        await broadcast(YouSaid(text=text))
        image = await asyncio.to_thread(eyes.look) if eyes and eyes_on["value"] else None
        await respond(text, image)


async def listen_loop() -> None:
    """The ears run globally now — one mic, no matter how many pages."""
    while True:
        try:
            text = ears.listen()
        except Exception as e:
            print(f"🥔 Ears hiccup: {type(e).__name__}: {e}")
            continue
        if text:
            await handle_user_text(text)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if vts:
        try:
            print("   Connecting to VTube Studio...")
            await vts.connect()
            await learn_expressions(await vts.expressions())
            print("   ...connected!")
        except OSError:
            raise RuntimeError("Can't reach VTube Studio — is it running with the API enabled?")

    loop = asyncio.get_running_loop()

    def on_hold(held: bool):
        # Fires on pynput's listener thread — hop onto the event loop.
        # Only fall back to idle if we were the ones who set "listening";
        # releasing the key mid-reply shouldn't interrupt "speaking".
        if held:
            state = "listening"
        elif current_state["value"] == "listening":
            state = "idle"
        else:
            return
        asyncio.run_coroutine_threadsafe(set_state(state), loop)

    ears.on_hold = on_hold

    def ears_loop():
        # A daemon thread, NOT asyncio.to_thread: keyboard.wait() blocks
        # forever, and Python joins pool threads at shutdown — which is
        # exactly how you make Ctrl+C hang. Daemon threads just die.
        while True:
            text = ears.listen()
            if text:
                # We're in thread-land; hand the work to the event loop
                # and wait for her to finish before listening again.
                asyncio.run_coroutine_threadsafe(
                    handle_user_text(text), loop
                ).result()

    threading.Thread(target=ears_loop, daemon=True).start()
    yield


app = FastAPI(lifespan=lifespan)

@app.middleware("http")
async def no_cache(request, call_next):
    """Localhost doesn't need caching.
    Tell every client to always fetch fresh."""
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response

@app.get("/config")
async def get_config():
    return {
        "character": {"name": config.character.name},
        "face": config.face,
        "expressions": scan_expressions(config.face.model),
    }


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    clients.add(ws)
    await ws.send_text(eyes_state().model_dump_json())
    await ws.send_text(history().model_dump_json())
    await ws.send_text(tools_state().model_dump_json())
    try:
        while True:
            data = await ws.receive_json()
            if data.get("type") == "model_info":
                await learn_expressions(data.get("expressions", []))
            elif data.get("type") == "user_says":
                text = data["text"].strip()
                if text:
                    await handle_user_text(text)
            elif data.get("type") == "now_saying":
                await broadcast(NowSaying(text=data.get("text", "")))
            elif data.get("type") == "set_eyes" and eyes:
                eyes_on["value"] = bool(data.get("enabled"))
                await broadcast(eyes_state())
    except WebSocketDisconnect:
        pass
    finally:
        clients.discard(ws)


app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.server.host, port=config.server.port, timeout_graceful_shutdown=1)