"""The potato's voice: turns text into speech audio, one chunk at a time.

Powered by Kyutai's Pocket TTS. Give it a short voice sample (any clean
recording of one person talking) and she'll speak in that voice.

Try it standalone:
    uv run python -m potatuber.voice "Hello! I'm your potato."
"""

import re
from pathlib import Path
from typing import Iterator

import numpy as np
import soundfile as sf
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


def _write_lowered(src: Path, dst: Path, ratio: float) -> None:
    """Stretch the clip by `ratio` so it plays slower and deeper.

    This deeper, "bigger-voiced" version is what the model actually clones —
    it sits comfortably inside what Pocket TTS has heard before. Listen to
    this file if a voice sounds off: it should sound like a natural person.
    """
    audio, sr = sf.read(src, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    positions = np.linspace(0, len(audio) - 1, round(len(audio) * ratio))
    lowered = np.interp(positions, np.arange(len(audio)), audio)
    sf.write(dst, lowered.astype(np.float32), sr)


class Voice:
    def __init__(self, voice_sample: str | Path, pitch_shift: float = 0.0, language: str = "english"):
        """Load the TTS model and prepare the voice.

        The first time a voice sample is used, computing its "voice state"
        takes a little while — so we save the result next to the sample
        (as a .safetensors file) and load that instantly ever after.
        
        pitch_shift (semitones, e.g. 3.0): for squeaky/cartoon voices the
        tiny model gets crunchy up high. So we clone a *lowered* copy of the
        sample, then play the output back faster to lift it right back up.
        The lift is free: self.sample_rate already includes it.

        language: which Pocket TTS model to load — a language name, optionally
        with "_24l" for the big "teacher" model the small one was distilled
        from. Cleaner voices, ~3x slower. The cache is per model, since the
        voice state's shape depends on the layer count.
        """
        self.model = TTSModel.load_model(language=language)
        self.ratio = 2 ** (pitch_shift / 12)
        self.sample_rate: int = round(self.model.sample_rate * self.ratio)

        voice_sample = Path(voice_sample)
        shift_tag = f".shift{pitch_shift:+g}" if pitch_shift else ""
        prompt = voice_sample
        if pitch_shift:
            prompt = voice_sample.with_name(f"{voice_sample.stem}{shift_tag}.wav")
            if not prompt.exists():
                _write_lowered(voice_sample, prompt, self.ratio)

        # The voice state's shape depends on the model, so each one gets its own.
        cached = voice_sample.with_name(f"{voice_sample.stem}{shift_tag}.{language}.safetensors")
        if not cached.exists():
            state = self.model.get_state_for_audio_prompt(str(prompt))
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
    voice = Voice(config.voice.sample, config.voice.pitch_shift, config.voice.language)

    with sd.OutputStream(
        samplerate=voice.sample_rate, channels=1, dtype="int16"
    ) as stream:
        for chunk in voice.say(text):
            stream.write(chunk)