"""The potato's ears: turns your voice into text.

Push-to-talk: hold the hotkey, say something, release. Your finger is
the voice activity detector — nothing is recorded until you press.

Powered by faster-whisper (Whisper via CTranslate2). The first run
downloads the model (~150 MB for base.en) and caches it.

Try it standalone:
    uv run python -m potatuber.ears
"""

import re
import threading

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
from pynput import keyboard

SAMPLE_RATE = 16000  # Whisper only speaks 16 kHz mono
MIN_SPEECH = 0.3  # seconds — shorter than this is a tap, not speech


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def _looks_like(text: str, prompt: str) -> bool:
    """True if the transcription is really just the prompt echoed back."""
    a, b = _normalize(text), _normalize(prompt)
    return bool(a) and (a in b or b in a)


def _parse_key(name: str):
    """Turn a config string like "tab" or "a" into a pynput key object."""
    if hasattr(keyboard.Key, name):
        return getattr(keyboard.Key, name)  # special keys: tab, space, ctrl_r...
    return keyboard.KeyCode.from_char(name)  # ordinary letters and digits


class Ears:
    def __init__(self, whisper_model: str, hotkey: str, prompt: str = ""):
        self.model = WhisperModel(whisper_model, device="cpu", compute_type="int8")
        self.prompt = prompt
        self.hotkey = hotkey
        self._key = _parse_key(hotkey)
        self._held = threading.Event()
        self.on_hold = None  # optional: called with True on press, False on release
        self._timer = None
        self._announced = False

        # One listener for the whole session. It runs in its own thread and
        # just flips a flag — listen() watches that flag.
        listener = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release
        )
        listener.daemon = True
        listener.start()

    def _on_press(self, key):
        if key == self._key and not self._held.is_set():
            self._held.set()
            # Announce "listening" only once the tap-grace period has passed —
            # a quick tap records nothing, so the dot shouldn't flicker.
            self._timer = threading.Timer(MIN_SPEECH, self._announce)
            self._timer.daemon = True
            self._timer.start()

    def _announce(self):
        if self._held.is_set() and self.on_hold:
            self._announced = True
            self.on_hold(True)

    def _on_release(self, key):
        if key == self._key:
            self._held.clear()
            if self._timer:
                self._timer.cancel()
            if self._announced:
                self._announced = False
                if self.on_hold:
                    self.on_hold(False)

    def listen(self) -> str:
        """Block until the user holds the hotkey and speaks. Returns the text."""
        self._held.wait()

        recorded = []

        def callback(indata, frames, time, status):
            recorded.append(indata.copy())

        with sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=callback
        ):
            while self._held.is_set():
                sd.sleep(50)

        audio = np.concatenate(recorded)[:, 0] if recorded else np.zeros(0, np.float32)
        if len(audio) < SAMPLE_RATE * MIN_SPEECH:
            return ""  # a tap, not speech — Whisper hallucinates on tiny clips
        segments, _ = self.model.transcribe(audio, initial_prompt=self.prompt or None)
        text = " ".join(s.text for s in segments).strip()

        if self.prompt and _looks_like(text, self.prompt):
            return ""
        return text


if __name__ == "__main__":
    from potatuber.config import load

    config = load()
    ears = Ears(config.ears.whisper_model, config.ears.hotkey)
    print(f"🥔 Hold [{ears.hotkey}] and speak. Ctrl+C to quit.")
    while True:
        print(f"You said: {ears.listen()!r}")