"""The contract between the potato's body (Python) and her face (browser).

Every message is one JSON object with a "type" field. That's the whole
protocol. If you can read this file, you can write your own frontend.
"""

from typing import Literal

from pydantic import BaseModel


# ── Server → Browser ──────────────────────────────────────────


class State(BaseModel):
    """What the character is currently doing. Drives animations."""
    type: Literal["state"] = "state"
    state: Literal["idle", "listening", "thinking", "speaking"]


class YouSaid(BaseModel):
    """What Whisper heard the user say. Show it as a subtitle."""
    type: Literal["you_said"] = "you_said"
    text: str


class SpeakStart(BaseModel):
    """The character is about to say this sentence. Show it as her subtitle."""
    type: Literal["speak_start"] = "speak_start"
    text: str


class AudioChunk(BaseModel):
    """A chunk of speech audio, base64-encoded 16-bit PCM.

    The frontend computes mouth openness from this audio's volume.
    The backend doesn't know the puppet has a mouth. It's better that way.
    """
    type: Literal["audio_chunk"] = "audio_chunk"
    data: str
    sample_rate: int = 24000


class SpeakEnd(BaseModel):
    """She's done talking. Close the mouth, go back to idle."""
    type: Literal["speak_end"] = "speak_end"


class SetExpression(BaseModel):
    """She decided to make a face. The name comes from the model's own
    expression list (see ModelInfo), so this works with any Live2D model."""
    type: Literal["set_expression"] = "set_expression"
    name: str


# ── Browser → Server ──────────────────────────────────────────


class ModelInfo(BaseModel):
    """Sent once when the frontend loads the Live2D model. Tells the brain
    what faces she's capable of making. Empty list = no expression tool."""
    type: Literal["model_info"] = "model_info"
    expressions: list[str]

class UserSays(BaseModel):
    """The user typed something at her. (Temporary stand-in for ears.py —
    once she can hear, this becomes the debug/fallback input.)"""
    type: Literal["user_says"] = "user_says"
    text: str

class NowSaying(BaseModel):
    """What she's saying RIGHT NOW — playback-time, not generation-time.

    Sent by the mascot page (the only one who knows when audio actually
    plays) and rebroadcast to everyone. The subtitle window just displays
    whatever arrives. Empty text means "she finished, clear the screen."
    """
    type: Literal["now_saying"] = "now_saying"
    text: str