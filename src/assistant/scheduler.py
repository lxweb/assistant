import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

_DURATION_RE = re.compile(
    r"^(\d+)\s*(m|min|mins|minuto|minutos|h|hr|hora|horas|d|dia|dias)$",
    re.IGNORECASE,
)


@dataclass
class ScheduledTask:
    id: int
    user_id: int
    description: str
    run_at: str
    status: str


class SchedulerStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    async def init(self) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS scheduled_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    description TEXT NOT NULL,
                    run_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL
                )
                """
            )
            await db.commit()

    async def schedule(
        self, user_id: int, description: str, run_at: datetime
    ) -> ScheduledTask:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO scheduled_tasks
                (user_id, description, run_at, status, created_at)
                VALUES (?, ?, ?, 'pending', ?)
                """,
                (user_id, description, run_at.isoformat(), now),
            )
            await db.commit()
            task_id = cursor.lastrowid
        return await self.get(task_id)

    async def get(self, task_id: int) -> ScheduledTask:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM scheduled_tasks WHERE id = ?", (task_id,)
            )
            row = await cursor.fetchone()
        if row is None:
            raise KeyError(task_id)
        return _row_to_scheduled(row)

    async def list_pending_due(self) -> list[ScheduledTask]:
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM scheduled_tasks
                WHERE status = 'pending' AND run_at <= ?
                ORDER BY run_at ASC
                """,
                (now,),
            )
            rows = await cursor.fetchall()
        return [_row_to_scheduled(r) for r in rows]

    async def mark_done(self, task_id: int) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "UPDATE scheduled_tasks SET status = 'done' WHERE id = ?",
                (task_id,),
            )
            await db.commit()

    async def list_by_user(self, user_id: int, limit: int = 10) -> list[ScheduledTask]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM scheduled_tasks
                WHERE user_id = ? AND status = 'pending'
                ORDER BY run_at ASC
                LIMIT ?
                """,
                (user_id, limit),
            )
            rows = await cursor.fetchall()
        return [_row_to_scheduled(r) for r in rows]


def parse_schedule_args(args: list[str]) -> tuple[datetime, str] | None:
    if len(args) < 2:
        return None

    when_raw = args[0].lower()
    description = " ".join(args[1:]).strip()
    if not description:
        return None

    now = datetime.now(timezone.utc)
    match = _DURATION_RE.match(when_raw)
    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()[0]
        if unit == "m":
            delta = timedelta(minutes=amount)
        elif unit == "h":
            delta = timedelta(hours=amount)
        else:
            delta = timedelta(days=amount)
        return now + delta, description

    try:
        run_at = datetime.fromisoformat(when_raw)
        if run_at.tzinfo is None:
            run_at = run_at.replace(tzinfo=timezone.utc)
        return run_at, description
    except ValueError:
        return None


async def scheduler_loop(app, interval: int) -> None:
    while True:
        try:
            store: SchedulerStore = app.bot_data["scheduler"]
            process = app.bot_data["process_user_message"]
            due = await store.list_pending_due()
            for item in due:
                await store.mark_done(item.id)
                await app.bot.send_message(
                    chat_id=item.user_id,
                    text=f"⏰ Recordatorio #{item.id}: {item.description}",
                )
                await process(app, item.user_id, item.description)
        except Exception:
            logger.exception("Error en scheduler loop")
        await asyncio.sleep(interval)


def _row_to_scheduled(row: aiosqlite.Row) -> ScheduledTask:
    return ScheduledTask(
        id=row["id"],
        user_id=row["user_id"],
        description=row["description"],
        run_at=row["run_at"],
        status=row["status"],
    )
