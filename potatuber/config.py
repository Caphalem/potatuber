"""Loads and validates config.toml — the file where the potato is customized.

Every part asks this module for its settings instead of hardcoding them.
If something in config.toml is wrong, pydantic tells you exactly what
and where, instead of crashing mysteriously later.
"""

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class CharacterConfig(BaseModel):
    name: str
    system_prompt: str
    reminder: str


class BrainConfig(BaseModel):
    base_url: str
    model: str
    api_key: str = "potato"
    max_history: int = 24000


class VoiceConfig(BaseModel):
    sample: str
    stream_audio: bool = False
    pitch_shift: float = 0.0
    language: str = "english"
    volume: float = 1.0


class FaceConfig(BaseModel):
    model: str
    follow_mouse: bool = True
    follow_rate: int = 15
    mouth_params: list[str] = ["ParamMouthOpenY", "ParamMouthOpen", "MouthOpen"]
    mouth_gain: float = 6
    idle_motion: str = ""
    toggles: list[str] = []
    mouth_form_param: str = "ParamMouthForm"
    mouth_form_range: list[float] = [1750, 2800]


class EarsConfig(BaseModel):
    whisper_model: str = "base.en"
    hotkey: str = "shift_r"
    prompt: str = "Pota-chan, PotaTuber, Live2D"
    input_device: str = ""


class EyesConfig(BaseModel):
    enabled: bool = False
    max_width: int = 1280
    monitor: int = 1


class MascotConfig(BaseModel):
    width: int = 400
    height: int = 650
    x: int = 1136
    y: int = 214
    toggle_hotkey: str = "ctrl+alt+p"


class VtsConfig(BaseModel):
    enabled: bool = False
    port: int = 8001
    mode: Literal["model", "item"] = "model"
    item_name: str = "PotaChan"
    mouth_param: str = "MouthOpen"
    mouth_gain: float = 6
    mouth_form_param: str = "MouthSmile"
    expressions: list[str] = ""
    output_device: str = ""


class SubtitlesConfig(BaseModel):
    width: int = 800
    height: int = 120
    x: int = 368
    y: int = 700


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8158


class Config(BaseModel):
    character: CharacterConfig
    brain: BrainConfig
    voice: VoiceConfig
    ears: EarsConfig
    eyes: EyesConfig
    face: FaceConfig
    mascot: MascotConfig
    vts: VtsConfig
    subtitles: SubtitlesConfig
    server: ServerConfig


def load(path: str | Path = "config.toml") -> Config:
    with open(path, "rb") as f:
        return Config(**tomllib.load(f))