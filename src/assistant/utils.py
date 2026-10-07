import time
from collections import defaultdict, deque

from telegram import Bot
from telegram.constants import ParseMode


class RateLimiter:
    def __init__(self, max_per_minute: int) -> None:
        self._max = max_per_minute
        self._hits: dict[int, deque[float]] = defaultdict(deque)

    def allow(self, user_id: int) -> bool:
        now = time.monotonic()
        window = self._hits[user_id]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= self._max:
            return False
        window.append(now)
        return True


async def send_long_message(
    bot: Bot,
    chat_id: int,
    text: str,
    parse_mode: str | None = ParseMode.MARKDOWN,
    chunk_size: int = 4000,
) -> None:
    if len(text) <= chunk_size:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
        return

    start = 0
    while start < len(text):
        chunk = text[start : start + chunk_size]
        await bot.send_message(chat_id=chat_id, text=chunk, parse_mode=parse_mode)
        start += chunk_size
