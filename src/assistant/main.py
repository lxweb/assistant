import logging
import sys

from assistant.agent import TaskAgent
from assistant.bot import build_application
from assistant.config import Config
from assistant.tasks import TaskStore


def main() -> None:
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )

    try:
        config = Config.from_env()
    except ValueError as exc:
        print(f"Error de configuración: {exc}", file=sys.stderr)
        print("Copia .env.example a .env y completa los valores.", file=sys.stderr)
        sys.exit(1)

    store = TaskStore(config.database_path)
    agent = TaskAgent(config)
    app = build_application(config, store, agent)

    logging.info("Iniciando bot de Telegram...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
