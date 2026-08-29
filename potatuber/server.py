"""The potato's nervous system: connects the Python organs to her faces.

Plural faces! Any number of pages can connect to the WebSocket at once:
the mascot window, the console, a subtitle overlay... Every event is
broadcast to all of them, and input can come from any of them (or from
the ears, which live here in Python-land).
"""

import asyncio
import base64
from contextlib import asynccontextmanager
import threading
import time

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from openai import APIConnectionError

from potatuber.brain import Brain
from potatuber.config import load
from potatuber.ears import Ears
from potatuber.events import AudioChunk, NowSaying, SpeakEnd, SpeakStart, State, YouSaid
from potatuber.hands import make_default_hands
from potatuber.voice import Voice, make_speakable

print("🥔 Waking up the potato...")

config = load()

t = time.perf_counter()
print("   Loading voice (Pocket TTS)...")
voice = Voice(config.voice.sample)
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
ears = Ears(config.ears.whisper_model, config.ears.hotkey)
print(f"   ...ears ready in {time.perf_counter() - t:.1f}s")

print("🥔 All organs ready!")

clients: set[WebSocket] = set()

# One conversation at a time: if the ears and the console both submit,
# the second one politely waits its turn instead of interleaving.
conversation_lock = asyncio.Lock()


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
    if config.voice.stream_audio:
        while (chunk := await asyncio.to_thread(next, chunks, None)) is not None:
            await send_audio(chunk)
    else:
        all_chunks = await asyncio.to_thread(list, chunks)
        await send_audio(np.concatenate(all_chunks))

    await broadcast(SpeakEnd())


async def respond(user_text: str) -> None:
    await broadcast(State(state="thinking"))

    try:
        items = brain.think(user_text)
        await broadcast(State(state="speaking"))
        while (item := await asyncio.to_thread(next, items, None)) is not None:
            kind, payload = item
            if kind == "event":
                await broadcast(payload)
            else:
                await speak(payload)
    except APIConnectionError:
        print("🥔 Can't reach the brain! Is LM Studio running, with the "
              f"server on, at {config.brain.base_url}?")
        await speak("I can't reach my brain right now...")

    await broadcast(State(state="idle"))


async def handle_user_text(text: str) -> None:
    """The one entrance for ALL input — ears, console, whatever comes later."""
    async with conversation_lock:
        await broadcast(YouSaid(text=text))
        await respond(text)


async def listen_loop() -> None:
    """The ears run globally now — one mic, no matter how many pages."""
    while True:
        text = await asyncio.to_thread(ears.listen)
        if text:
            await handle_user_text(text)


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()

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
    return config.face


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    clients.add(ws)
    try:
        while True:
            data = await ws.receive_json()
            if data.get("type") == "model_info":
                expressions = data.get("expressions", [])
                brain.hands = make_default_hands(expressions)
                if expressions:
                    brain.add_instructions(
                        f"You can change your look with the set_expression "
                        f"tool. Your available faces: {', '.join(expressions)}. "
                        f"Use them to react!"
                    )
            elif data.get("type") == "user_says":
                text = data["text"].strip()
                if text:
                    await handle_user_text(text)
            elif data.get("type") == "now_saying":
                await broadcast(NowSaying(text=data.get("text", "")))
    except WebSocketDisconnect:
        pass
    finally:
        clients.discard(ws)


app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.server.host, port=config.server.port, timeout_graceful_shutdown=1)