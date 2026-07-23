"""Server-side voice input (§7 follow-up): the browser's native Web Speech
API only covers Chrome/Edge, so this gives Safari/Firefox/mobile a working
voice path -- transcription via Groq Whisper, which the app already has a
client/API key for (see ../groq_client.py), so this is additive, not a new
vendor integration."""

from groq import GroqError

from ..groq_client import groq_client

_MODEL = "whisper-large-v3-turbo"


class TranscriptionError(Exception):
    pass


def transcribe_audio(audio_bytes: bytes, filename: str, content_type: str | None) -> str:
    try:
        result = groq_client.audio.transcriptions.create(
            model=_MODEL,
            file=(filename, audio_bytes, content_type),
        )
    except GroqError as exc:
        raise TranscriptionError(str(exc)) from exc
    return result.text.strip()
