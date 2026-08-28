"""The potato's ears: turns your voice into text.

Push-to-talk: hold the hotkey, say something, release. Your finger is
the voice activity detector — nothing is recorded until you press.

Powered by faster-whisper (Whisper via CTranslate2). The first run
downloads the model (~150 MB for base.en) and caches it.

Try it standalone:
    uv run python -m potatuber.ears
"""

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

SAMPLE_RATE = 16000  # Whisper only speaks 16 kHz mono


class Ears:
    def __init__(self, whisper_model: str, hotkey: str):
        # int8 quantization: the "runs fine on a potato" compute type.
        self.model = WhisperModel(whisper_model, device="cpu", compute_type="int8")
        self.hotkey = hotkey

    def listen(self) -> str:
        """Block until the user holds the hotkey and speaks. Returns the text.

        Recording runs only while the key is held. Whisper runs only after
        release. Between presses, the ears cost nothing. Keeps the potato cool.
        """
        import keyboard

        keyboard.wait(self.hotkey)

        recorded = []

        def callback(indata, frames, time, status):
            recorded.append(indata.copy())

        with sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=callback
        ):
            while keyboard.is_pressed(self.hotkey):
                sd.sleep(50)

        audio = np.concatenate(recorded)[:, 0]
        segments, _ = self.model.transcribe(audio)
        return " ".join(s.text for s in segments).strip()


if __name__ == "__main__":
    from potatuber.config import load

    config = load()
    ears = Ears(config.ears.whisper_model, config.ears.hotkey)
    print(f"🥔 Hold [{ears.hotkey}] and speak. Ctrl+C to quit.")
    while True:
        print(f"You said: {ears.listen()!r}")