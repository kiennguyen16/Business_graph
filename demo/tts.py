"""Synthesize narration clips as mono, 24 kHz PCM wave files."""

import json
import os
import subprocess
import wave
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from dotenv import load_dotenv

SAMPLE_RATE = 24000


def select_engine(engine):
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    if engine == "auto":
        return "elevenlabs" if os.getenv("ELEVENLABS_API_KEY") else "kokoro"
    return engine


def make_synthesizer(engine, ffmpeg):
    if engine == "elevenlabs":
        key = os.getenv("ELEVENLABS_API_KEY")
        if not key:
            raise ValueError("Set ELEVENLABS_API_KEY in the environment or repository .env.")
        voice = quote(os.getenv("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb"), safe="")
        model = os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")

        def synthesize(text, path):
            request = Request(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128",
                data=json.dumps({"text": text, "model_id": model}).encode(),
                headers={"xi-api-key": key, "Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urlopen(request, timeout=60) as response:
                    audio = response.read()
            except HTTPError as error:
                raise RuntimeError(f"ElevenLabs returned HTTP {error.code}.") from None
            except (URLError, TimeoutError):
                raise RuntimeError("Could not reach ElevenLabs.") from None
            subprocess.run(
                [ffmpeg, "-v", "error", "-y", "-i", "pipe:0", "-ac", "1",
                 "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", str(path)],
                input=audio, check=True,
            )

        return synthesize

    if engine == "kokoro":
        import numpy as np
        import soundfile
        import torch
        from kokoro import KPipeline

        voice = os.getenv("KOKORO_VOICE", "bf_emma")
        speed = float(os.getenv("KOKORO_SPEED", "1.14"))
        torch.set_num_threads(min(4, os.cpu_count() or 1))
        pipeline = KPipeline(lang_code=voice[0], repo_id="hexgrad/Kokoro-82M", device="cpu")

        def synthesize(text, path):
            chunks = [result.audio.numpy() for result in pipeline(text, voice=voice, speed=speed)]
            soundfile.write(path, np.concatenate(chunks), SAMPLE_RATE, subtype="PCM_16")

        return synthesize

    if engine == "piper":
        from piper import PiperVoice

        model = os.getenv("PIPER_VOICE_MODEL")
        if not model:
            raise ValueError("Set PIPER_VOICE_MODEL to the path of the Piper .onnx voice.")
        voice = PiperVoice.load(model)

        def synthesize(text, path):
            raw = path.with_suffix(".piper.wav")
            with wave.open(str(raw), "wb") as output:
                voice.synthesize_wav(text, output)
            subprocess.run(
                [ffmpeg, "-v", "error", "-y", "-i", str(raw), "-ac", "1",
                 "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", str(path)],
                check=True,
            )
            raw.unlink()

        return synthesize

    raise ValueError(f"Unknown TTS engine: {engine}")


def duration(path):
    with wave.open(str(path), "rb") as clip:
        return clip.getnframes() / clip.getframerate()
