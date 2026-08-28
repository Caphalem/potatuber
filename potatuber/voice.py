"""The potato's voice: turns text into speech audio, one chunk at a time.

Powered by Kyutai's Pocket TTS. Give it a short voice sample (any clean
recording of one person talking) and she'll speak in that voice.

Try it standalone:
    uv run python -m potatuber.voice "Hello! I'm your potato."
"""

from pathlib import Path
from typing import Iterator

import numpy as np
import re
from pocket_tts import TTSModel, export_model_state

# Matches emoji and other symbols Pocket TTS can't pronounce.
UNSPEAKABLE = re.compile(
    "["
    "\U0001f300-\U0001faff"  # emoji blocks (symbols, emoticons, potatoes)
    "\U00002600-\U000027bf"  # misc symbols, dingbats
    "\u2728\u2764\ufe0f"     # a few strays that live outside the blocks
    "]+"
)


def make_speakable(text: str) -> str:
    """Strip emojis and markdown decoration so TTS doesn't choke on them.

    LLM output is DISPLAY text; this turns it into SPEECH text.
    The subtitle shows what she wrote — her voice says what matters.
    """
    text = UNSPEAKABLE.sub("", text)
    text = re.sub(r"[*_#`~]+", "", text)  # markdown bold/italics/headers/code
    return text.strip()

class Voice:
    def __init__(self, voice_sample: str | Path):
        """Load the TTS model and prepare the voice.

        The first time a voice sample is used, computing its "voice state"
        takes a little while — so we save the result next to the sample
        (as a .safetensors file) and load that instantly ever after.
        """
        self.model = TTSModel.load_model()
        self.sample_rate: int = self.model.sample_rate

        voice_sample = Path(voice_sample)
        cached = voice_sample.with_suffix(".safetensors")
        if not cached.exists():
            state = self.model.get_state_for_audio_prompt(str(voice_sample))
            export_model_state(state, str(cached))
        self.voice_state = self.model.get_state_for_audio_prompt(str(cached))

    def say(self, text: str) -> Iterator[np.ndarray]:
        """Speak one sentence, yielding audio chunks as they're generated.

        Chunks are 1D int16 numpy arrays (standard 16-bit PCM) at
        self.sample_rate — ready to be played, saved, or sent to a browser.

        copy_state=True keeps our voice_state pristine, so every sentence
        starts from the same clean voice otherwise each generation scribbles
        over the state and the voice degrades over time.
        """
        for chunk in self.model.generate_audio_stream(
            self.voice_state, text, copy_state=True
        ):
            float_audio = chunk.numpy().clip(-1.0, 1.0)
            yield (float_audio * 32767).astype(np.int16)


if __name__ == "__main__":
    import sys

    import sounddevice as sd

    from potatuber.config import load

    config = load()
    text = " ".join(sys.argv[1:]) or "Hello! I'm your potato. I can talk now!"
    voice = Voice(config.voice.sample)

    with sd.OutputStream(
        samplerate=voice.sample_rate, channels=1, dtype="int16"
    ) as stream:
        for chunk in voice.say(text):
            stream.write(chunk)