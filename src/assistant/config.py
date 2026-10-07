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
    vault_path: Path | None
    memory_max_messages: int
    shell_allowed_prefixes: frozenset[str]
    rate_limit_per_minute: int
    log_file: Path | None
    scheduler_interval_seconds: int
    health_host: str
    health_port: int
    wekan_api_url: str | None
    wekan_api_token: str | None
    wekan_author_id: str | None
    wekan_user_id: str | None
    wekan_public_url: str

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

        vault_raw = os.getenv("VAULT_PATH", "").strip()
        vault_path = Path(vault_raw) if vault_raw else None

        shell_raw = os.getenv(
            "SHELL_ALLOWED_PREFIXES",
            "ls,cat,head,tail,grep,find,git status,git log,ollama list,ollama ps",
        )
        shell_prefixes = frozenset(
            p.strip() for p in shell_raw.split(",") if p.strip()
        )

        log_raw = os.getenv("LOG_FILE", "").strip()
        log_file = Path(log_raw) if log_raw else None
        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)

        return cls(
            telegram_bot_token=token,
            telegram_allowed_users=allowed_users,
            openai_api_key=api_key,
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            openai_base_url=os.getenv("OPENAI_BASE_URL") or None,
            database_path=db_path,
            vault_path=vault_path,
            memory_max_messages=int(os.getenv("MEMORY_MAX_MESSAGES", "20")),
            shell_allowed_prefixes=shell_prefixes,
            rate_limit_per_minute=int(os.getenv("RATE_LIMIT_PER_MINUTE", "10")),
            log_file=log_file,
            scheduler_interval_seconds=int(
                os.getenv("SCHEDULER_INTERVAL_SECONDS", "30")
            ),
            health_host=os.getenv("HEALTH_HOST", "127.0.0.1"),
            health_port=int(os.getenv("HEALTH_PORT", "8080")),
            wekan_api_url=os.getenv("WEKAN_API_URL") or None,
            wekan_api_token=os.getenv("WEKAN_API_TOKEN") or None,
            wekan_author_id=os.getenv("WEKAN_AUTHOR_ID") or None,
            wekan_user_id=os.getenv("WEKAN_USER_ID") or None,
            wekan_public_url=os.getenv("WEKAN_PUBLIC_URL", "http://wekan.home.lan"),
        )
