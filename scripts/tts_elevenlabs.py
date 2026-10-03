"""Narration with ElevenLabs text-to-speech, cached per line. The key is read from ELEVENLABS_API_KEY
(environment or the gitignored .env written by scripts/set_elevenlabs_key.sh) and is never printed or logged.

    .venv/bin/python scripts/tts_elevenlabs.py --voices              # list available voices
    .venv/bin/python scripts/tts_elevenlabs.py --sample "text" --voice Brian --out /tmp/x.mp3
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import requests

API = "https://api.elevenlabs.io/v1"
CACHE = Path("data/tts_cache")
MODEL = "eleven_multilingual_v2"
SETTINGS = {"stability": 0.38, "similarity_boost": 0.8, "style": 0.35, "use_speaker_boost": True}


def _key() -> str:
    k = os.environ.get("ELEVENLABS_API_KEY")
    if not k and Path(".env").exists():
        for line in Path(".env").read_text().splitlines():
            if line.startswith("ELEVENLABS_API_KEY="):
                k = line.split("=", 1)[1].strip()
    if not k:
        raise SystemExit("No ElevenLabs key: run  bash scripts/set_elevenlabs_key.sh")
    return k


def voices() -> list[dict]:
    r = requests.get(f"{API}/voices", headers={"xi-api-key": _key()}, timeout=30)
    r.raise_for_status()
    return [{"name": v["name"], "voice_id": v["voice_id"], "labels": v.get("labels", {})} for v in r.json()["voices"]]


def voice_id(name: str) -> str:
    for v in voices():
        if v["name"].lower().startswith(name.lower()):
            return v["voice_id"]
    raise SystemExit(f"voice {name!r} not found")


def synth(text: str, out: Path, voice: str = "Brian", model: str = MODEL, settings: dict | None = None,
          previous_text: str | None = None, next_text: str | None = None) -> Path:
    """Render one narration line to MP3 (cached by text, voice, model and settings)."""
    settings = settings or SETTINGS
    tag = hashlib.sha256(json.dumps([text, voice, model, settings, previous_text, next_text]).encode()).hexdigest()[:20]
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / f"{tag}.mp3"
    if not cached.exists():
        body = {"text": text, "model_id": model, "voice_settings": settings}
        if previous_text:
            body["previous_text"] = previous_text
        if next_text:
            body["next_text"] = next_text
        r = requests.post(f"{API}/text-to-speech/{voice_id(voice)}?output_format=mp3_44100_128",
                          headers={"xi-api-key": _key(), "Content-Type": "application/json"}, json=body, timeout=120)
        if r.status_code != 200:
            raise SystemExit(f"ElevenLabs error {r.status_code}: {r.text[:200]}")
        cached.write_bytes(r.content)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(cached.read_bytes())
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--voices", action="store_true")
    ap.add_argument("--sample")
    ap.add_argument("--voice", default="Brian")
    ap.add_argument("--out", default="results/viz/voice_sample.mp3")
    a = ap.parse_args()
    if a.voices:
        for v in voices():
            print(f"{v['name']:<22} {v['labels'].get('accent', ''):<12} {v['labels'].get('description', '')} {v['labels'].get('use_case', '')}")
    elif a.sample:
        print("wrote", synth(a.sample, Path(a.out), voice=a.voice))
