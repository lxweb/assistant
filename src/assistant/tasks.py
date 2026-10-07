from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

import aiosqlite


class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Task:
    id: int
    user_id: int
    description: str
    status: TaskStatus
    result: str | None
    created_at: str
    updated_at: str


class TaskStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    async def init(self) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    result TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            await db.commit()

    async def create(self, user_id: int, description: str) -> Task:
        now = _now_iso()
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO tasks (user_id, description, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, description, TaskStatus.PENDING.value, now, now),
            )
            await db.commit()
            task_id = cursor.lastrowid
        return await self.get(task_id)

    async def get(self, task_id: int) -> Task:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            )
            row = await cursor.fetchone()
        if row is None:
            raise KeyError(f"Tarea {task_id} no encontrada")
        return _row_to_task(row)

    async def list_by_user(
        self, user_id: int, limit: int = 10
    ) -> list[Task]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM tasks
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, limit),
            )
            rows = await cursor.fetchall()
        return [_row_to_task(row) for row in rows]

    async def update_status(
        self,
        task_id: int,
        status: TaskStatus,
        result: str | None = None,
    ) -> Task:
        now = _now_iso()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                UPDATE tasks
                SET status = ?, result = ?, updated_at = ?
                WHERE id = ?
                """,
                (status.value, result, now, task_id),
            )
            await db.commit()
        return await self.get(task_id)

    async def get_pending(self) -> list[Task]:
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM tasks
                WHERE status = ?
                ORDER BY id ASC
                """,
                (TaskStatus.PENDING.value,),
            )
            rows = await cursor.fetchall()
        return [_row_to_task(row) for row in rows]

    async def recover_stuck(self) -> int:
        """Re-queue tasks left in processing (e.g. after crash)."""
        now = _now_iso()
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """
                UPDATE tasks
                SET status = ?, updated_at = ?
                WHERE status = ?
                """,
                (TaskStatus.PENDING.value, now, TaskStatus.PROCESSING.value),
            )
            await db.commit()
            return cursor.rowcount

    async def count_by_status(self) -> dict[str, int]:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status"
            )
            rows = await cursor.fetchall()
        return {row[0]: row[1] for row in rows}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_task(row: aiosqlite.Row) -> Task:
    return Task(
        id=row["id"],
        user_id=row["user_id"],
        description=row["description"],
        status=TaskStatus(row["status"]),
        result=row["result"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


STATUS_EMOJI = {
    TaskStatus.PENDING: "⏳",
    TaskStatus.PROCESSING: "🔄",
    TaskStatus.COMPLETED: "✅",
    TaskStatus.FAILED: "❌",
}


def format_task(task: Task) -> str:
    emoji = STATUS_EMOJI.get(task.status, "❓")
    lines = [f"{emoji} *Tarea #{task.id}*", f"_{task.description}_"]
    if task.result:
        lines.append(f"\n{task.result}")
    return "\n".join(lines)


def format_task_list(tasks: list[Task]) -> str:
    if not tasks:
        return "No hay tareas registradas."
    return "\n\n".join(format_task(t) for t in tasks)
