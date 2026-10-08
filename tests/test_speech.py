import pytest
from httpx import Request, Response

from assistant.speech import SpeechClient


def _ok_json(payload: dict, url: str = "http://stt.test/v1/transcribe") -> Response:
    req = Request("POST", url)
    return Response(200, json=payload, request=req)


@pytest.mark.asyncio
async def test_transcribe_returns_text(monkeypatch):
    client = SpeechClient("http://stt.test", None)

    async def mock_post(self, url, **kwargs):
        assert url.endswith("/v1/transcribe")
        return _ok_json({"text": "hola mundo", "language": "es"}, url)

    async def mock_get(self, url, **kwargs):
        return Response(200, json={"status": "ok"})

    class FakeHttpx:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        post = mock_post
        get = mock_get

    monkeypatch.setattr("assistant.speech.httpx.AsyncClient", FakeHttpx)
    text = await client.transcribe(b"\x00", filename="voice.ogg")
    assert text == "hola mundo"


@pytest.mark.asyncio
async def test_stt_disabled():
    client = SpeechClient(None, None)
    assert not client.stt_enabled
    with pytest.raises(RuntimeError):
        await client.transcribe(b"data")
