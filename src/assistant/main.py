import logging
import sys
from logging.handlers import RotatingFileHandler

from assistant.agent import TaskAgent
from assistant.bot import build_application
from assistant.config import Config
from assistant.memory import ConversationStore
from assistant.scheduler import SchedulerStore
from assistant.tasks import TaskStore
from assistant.tools import ToolExecutor
from assistant.vault import VaultSearch
from assistant.wekan import WekanClient


def _setup_logging(log_file: str | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        handlers.append(
            RotatingFileHandler(
                log_file, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
            )
        )
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
        handlers=handlers,
    )


def main() -> None:
    try:
        config = Config.from_env()
    except ValueError as exc:
        print(f"Error de configuración: {exc}", file=sys.stderr)
        print("Copia .env.example a .env y completa los valores.", file=sys.stderr)
        sys.exit(1)

    _setup_logging(str(config.log_file) if config.log_file else None)

    store = TaskStore(config.database_path)
    memory = ConversationStore(config.database_path)
    scheduler = SchedulerStore(config.database_path)
    vault = VaultSearch(config.vault_path)
    wekan = None
    if (
        config.wekan_api_url
        and config.wekan_api_token
        and config.wekan_author_id
        and config.wekan_user_id
    ):
        wekan = WekanClient(
            config.wekan_api_url,
            config.wekan_api_token,
            config.wekan_author_id,
            config.wekan_user_id,
            config.wekan_public_url,
        )
    tools = ToolExecutor(config, vault, wekan)
    agent = TaskAgent(config, memory, tools)
    app = build_application(config, store, memory, scheduler, agent, wekan)

    logging.info("Iniciando bot de Telegram...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
