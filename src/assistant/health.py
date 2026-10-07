import asyncio
import json
import logging
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)


async def _handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    status_fn: Callable[[], Awaitable[dict]],
) -> None:
    try:
        request_line = (await reader.readline()).decode(errors="replace")
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break

        path = request_line.split(" ")[1] if " " in request_line else "/"
        if path == "/health":
            body = json.dumps(await status_fn()).encode()
            status = b"200 OK"
            content_type = b"application/json"
        else:
            body = b'{"error":"not found"}'
            status = b"404 Not Found"
            content_type = b"application/json"

        response = (
            b"HTTP/1.1 " + status + b"\r\n"
            b"Content-Type: " + content_type + b"\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n"
            b"\r\n" + body
        )
        writer.write(response)
        await writer.drain()
    except Exception:
        logger.exception("Error en health handler")
    finally:
        writer.close()
        await writer.wait_closed()


async def start_health_server(
    host: str,
    port: int,
    status_fn: Callable[[], Awaitable[dict]],
) -> asyncio.Server:
    async def _client_handler(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        await _handle_client(reader, writer, status_fn)

    server = await asyncio.start_server(_client_handler, host, port)
    logger.info("Health server en http://%s:%s/health", host, port)
    return server
