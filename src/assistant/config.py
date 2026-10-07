import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    telegram_allowed_users: frozenset[int]
    openai_api_key: str
    openai_model: str
    openai_base_url: str | None
    database_path: Path

    @classmethod
    def from_env(cls) -> "Config":
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN es requerido")

        allowed_raw = os.getenv("TELEGRAM_ALLOWED_USERS", "")
        allowed_users = frozenset(
            int(uid.strip()) for uid in allowed_raw.split(",") if uid.strip()
        )
        if not allowed_users:
            raise ValueError(
                "TELEGRAM_ALLOWED_USERS es requerido (IDs separados por coma)"
            )

        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise ValueError("OPENAI_API_KEY es requerido")

        db_path = Path(os.getenv("DATABASE_PATH", "data/tasks.db"))
        db_path.parent.mkdir(parents=True, exist_ok=True)

        return cls(
            telegram_bot_token=token,
            telegram_allowed_users=allowed_users,
            openai_api_key=api_key,
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            openai_base_url=os.getenv("OPENAI_BASE_URL") or None,
            database_path=db_path,
        )
