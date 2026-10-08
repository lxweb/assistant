import logging

import httpx

logger = logging.getLogger(__name__)


class SpeechClient:
    """Cliente HTTP para microservicios STT/TTS offline."""

    def __init__(
        self,
        stt_base_url: str | None,
        tts_base_url: str | None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self._stt = stt_base_url.rstrip("/") if stt_base_url else None
        self._tts = tts_base_url.rstrip("/") if tts_base_url else None
        self._timeout = timeout_seconds

    @property
    def stt_enabled(self) -> bool:
        return bool(self._stt)

    @property
    def tts_enabled(self) -> bool:
        return bool(self._tts)

    async def check_stt(self) -> bool:
        if not self._stt:
            return False
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self._stt}/health")
                return resp.status_code == 200
        except Exception:
            return False

    async def check_tts(self) -> bool:
        if not self._tts:
            return False
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self._tts}/health")
                return resp.status_code == 200
        except Exception:
            return False

    async def transcribe(
        self,
        audio_bytes: bytes,
        filename: str = "voice.ogg",
        language: str | None = None,
    ) -> str:
        if not self._stt:
            raise RuntimeError("STT no configurado (STT_BASE_URL)")

        data: dict[str, str] = {}
        if language:
            data["language"] = language

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._stt}/v1/transcribe",
                files={"file": (filename, audio_bytes, "application/octet-stream")},
                data=data,
            )
            if resp.status_code == 422:
                detail = resp.json().get("detail", "Sin habla detectada")
                raise ValueError(str(detail))
            resp.raise_for_status()
            payload = resp.json()
            text = (payload.get("text") or "").strip()
            if not text:
                raise ValueError("Transcripción vacía")
            return text

    async def synthesize_wav(self, text: str) -> bytes:
        if not self._tts:
            raise RuntimeError("TTS no configurado (TTS_BASE_URL)")

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._tts}/v1/synthesize",
                json={"text": text, "format": "wav"},
            )
            resp.raise_for_status()
            return resp.content
