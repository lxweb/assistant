from pathlib import Path

import aiosqlite

ACTIVE_WORKSPACE_KEY = "active_workspace"
ACTIVE_BOARD_KEY = "active_board"


class UserPrefsStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    async def init(self) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS user_prefs (
                    user_id INTEGER NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    PRIMARY KEY (user_id, key)
                )
                """
            )
            await db.commit()

    async def get(self, user_id: int, key: str) -> str | None:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT value FROM user_prefs WHERE user_id = ? AND key = ?",
                (user_id, key),
            )
            row = await cursor.fetchone()
        return row[0] if row else None

    async def set(self, user_id: int, key: str, value: str) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO user_prefs (user_id, key, value)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value
                """,
                (user_id, key, value),
            )
            await db.commit()

    async def delete(self, user_id: int, key: str) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "DELETE FROM user_prefs WHERE user_id = ? AND key = ?",
                (user_id, key),
            )
            await db.commit()

    async def get_active_workspace(self, user_id: int) -> str | None:
        return await self.get(user_id, ACTIVE_WORKSPACE_KEY)

    async def set_active_workspace(self, user_id: int, name: str) -> None:
        await self.set(user_id, ACTIVE_WORKSPACE_KEY, name.strip())

    async def get_active_board(self, user_id: int) -> str | None:
        return await self.get(user_id, ACTIVE_BOARD_KEY)

    async def set_active_board(self, user_id: int, name: str) -> None:
        await self.set(user_id, ACTIVE_BOARD_KEY, name.strip())
