"""The contract between the potato's body (Python) and her pages (browser).

Every message is one JSON object with a "type" field. That's the whole
protocol. The mascot, the console and the subtitle page all speak it, and
each one simply ignores the types it doesn't care about — so if you can read
this file, you can write your own frontend. (VTube Studio mode talks to VTS
through its own API instead; see vts.py.)
"""

from typing import Literal

from pydantic import BaseModel


# ── Server → Browser ──────────────────────────────────────────


class State(BaseModel):
    """What she's doing right now. The console shows it as the status pill;
    the face is free to use it for animations if you add some.

    "listening" means the push-to-talk key has been held past the tap-grace
    period. "speaking" starts when her first sentence is ready, and "idle"
    only returns once the face reports the last one has finished playing.
    """
    type: Literal["state"] = "state"
    state: Literal["idle", "listening", "thinking", "speaking"]


class YouSaid(BaseModel):
    """What the user said to her — heard by Whisper or typed in the console.
    Both arrive here identically, so pages can't tell the difference."""
    type: Literal["you_said"] = "you_said"
    text: str


class SpeakStart(BaseModel):
    """She's about to say this sentence. The console appends it to her reply
    right away; the face holds onto it and announces it as NowSaying only
    when the sentence's audio actually starts playing."""
    type: Literal["speak_start"] = "speak_start"
    text: str


class AudioChunk(BaseModel):
    """A chunk of speech audio, base64-encoded 16-bit PCM. One chunk per
    sentence when stream_audio is off, many small ones when it's on.

    The face computes mouth openness and vowel shape from this audio's
    volume and brightness. The backend doesn't know the puppet has a mouth.
    It's better that way.
    """
    type: Literal["audio_chunk"] = "audio_chunk"
    data: str
    sample_rate: int = 24000


class SpeakEnd(BaseModel):
    """All of this sentence's audio has been sent. The face uses it to work
    out when the sentence will finish playing, and clears the subtitle then
    (unless the next sentence has already taken over)."""
    type: Literal["speak_end"] = "speak_end"


class ResponseEnd(BaseModel):
    """Generation is finished — nothing more is coming for this reply. The
    face answers with PlaybackDone once the last of it has actually played,
    and only then does she go idle."""
    type: Literal["response_end"] = "response_end"


class SetExpression(BaseModel):
    """She decided to make a face, via her set_expression tool. Names are
    expression file names (Happy.exp3.json → "Happy"), found by scanning the
    model folder. "Neutral" is special: it clears whatever face she's making.
    In VTube Studio mode this never reaches the browser; the server sends it
    to VTS instead."""
    type: Literal["set_expression"] = "set_expression"
    name: str


class SetToggle(BaseModel):
    """She put on (or took off) an outfit piece, via her set_toggle tool.
    Toggles are expressions that STAY on until switched off — making a face
    doesn't remove them. Toggles that change the same parameters are
    mutually exclusive, so putting one on takes its siblings off."""
    type: Literal["set_toggle"] = "set_toggle"
    name: str
    on: bool


class EyesState(BaseModel):
    """Whether she's currently looking. Sent on connect and whenever it
    changes, so every open console shows the same switch position."""
    type: Literal["eyes_state"] = "eyes_state"
    available: bool  # eyes configured at all?
    enabled: bool    # ...and switched on right now?


class Seen(BaseModel):
    """The screenshot she was just sent, so you can check what she actually
    saw. Broadcast once per message while vision is on. Never stored anywhere
    — the same ephemeral rule as the image itself, which is why a console
    reload has nothing to show until the next message."""
    type: Literal["seen"] = "seen"
    image: str  # base64 JPEG, exactly the bytes her brain received


class History(BaseModel):
    """The conversation so far, sent to a page when it connects.

    Rebuilt from the brain's actual memory, so it's exactly what she
    remembers — no system prompt, and nothing she's already forgotten.
    Three kinds of entries, in the order they happened:

        {"role": "user",      "text": str}
        {"role": "assistant", "text": str}
        {"role": "tool",      "name": str, "args": dict | str, "result": str}

    The tool entry's args are a str only when her JSON was broken — shown raw.
    """
    type: Literal["history"] = "history"
    messages: list[dict]


class ToolUse(BaseModel):
    """She used one of her tools. Shown in the console so you can see what
    your potato is actually doing — the call, its arguments, and the result
    she was told."""
    type: Literal["tool_use"] = "tool_use"
    name: str
    args: dict | str   # str when her JSON was broken — shown raw
    result: str


class Tools(BaseModel):
    """The tools she currently has, with the exact descriptions her brain
    sees. Sent on connect and whenever they change — so you never have to
    argue with her about whether a tool exists."""
    type: Literal["tools"] = "tools"
    tools: list[dict]  # [{"name": str, "description": str}]


# ── Browser → Server ──────────────────────────────────────────


class ModelInfo(BaseModel):
    """Sent by the face every time it loads the Live2D model (so also on a
    page reload). Tells the brain what expressions she has, which become her
    set_expression and set_toggle tools. Sending this is also what marks a
    page as a *face* — the one the server waits on for PlaybackDone."""
    type: Literal["model_info"] = "model_info"
    expressions: list[str]


class UserSays(BaseModel):
    """The user typed something in the console. Goes through the exact same
    entrance as the ears, so typing and talking queue up together."""
    type: Literal["user_says"] = "user_says"
    text: str


class PlaybackDone(BaseModel):
    """The face's reply to ResponseEnd: the last sentence has finished
    playing through the speakers. Only now does she go idle, and only now
    does a queued message get its turn."""
    type: Literal["playback_done"] = "playback_done"


class SetEyes(BaseModel):
    """The user flipped the vision switch in the console."""
    type: Literal["set_eyes"] = "set_eyes"
    enabled: bool


# ── Both directions ───────────────────────────────────────────


class NowSaying(BaseModel):
    """What she's saying RIGHT NOW — playback-time, not generation-time.

    Whoever is playing the audio knows when it starts, so whoever that is
    sends this: the face in mascot and browser modes (and the server
    rebroadcasts it to everyone), or the server itself in VTube Studio
    mode, where Python plays the sound. The subtitle page just displays
    whatever arrives. Empty text means "she finished, clear the screen."
    """
    type: Literal["now_saying"] = "now_saying"
    text: str