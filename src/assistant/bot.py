import asyncio
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from assistant.agent import TaskAgent
from assistant.config import Config
from assistant.tasks import (
    TaskStatus,
    TaskStore,
    format_task,
    format_task_list,
)

logger = logging.getLogger(__name__)

HELP_TEXT = """\
*Comandos disponibles:*

/start — Iniciar el bot
/help — Mostrar esta ayuda
/tareas — Ver tus últimas tareas
/tarea \\<id\\> — Ver detalle de una tarea

*Asignar tareas:*
Simplemente envía un mensaje de texto con la tarea que quieres que procese.
Ejemplo: _"Resume los puntos clave de la reunión de ayer"_

El asistente procesará la tarea y te responderá cuando esté lista.\
"""


def _is_authorized(user_id: int | None, allowed: frozenset[int]) -> bool:
    return user_id is not None and user_id in allowed


async def _reject_unauthorized(update: Update) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(
            "No tienes permiso para usar este bot."
        )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config: Config = context.bot_data["config"]
    user = update.effective_user
    if not _is_authorized(user.id if user else None, config.telegram_allowed_users):
        await _reject_unauthorized(update)
        return

    await update.message.reply_text(
        f"Hola {user.first_name}! 👋\n\n"
        "Soy tu asistente personal. Envíame una tarea por mensaje "
        "y la procesaré por ti.\n\n"
        "Usa /help para ver los comandos disponibles.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config: Config = context.bot_data["config"]
    if not _is_authorized(
        update.effective_user.id if update.effective_user else None,
        config.telegram_allowed_users,
    ):
        await _reject_unauthorized(update)
        return

    await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.MARKDOWN_V2)


async def list_tasks_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    config: Config = context.bot_data["config"]
    store: TaskStore = context.bot_data["store"]
    user = update.effective_user

    if not _is_authorized(user.id if user else None, config.telegram_allowed_users):
        await _reject_unauthorized(update)
        return

    tasks = await store.list_by_user(user.id)
    await update.message.reply_text(
        format_task_list(tasks), parse_mode=ParseMode.MARKDOWN
    )


async def task_detail_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    config: Config = context.bot_data["config"]
    store: TaskStore = context.bot_data["store"]
    user = update.effective_user

    if not _is_authorized(user.id if user else None, config.telegram_allowed_users):
        await _reject_unauthorized(update)
        return

    if not context.args:
        await update.message.reply_text("Uso: /tarea <id>")
        return

    try:
        task_id = int(context.args[0])
        task = await store.get(task_id)
    except (ValueError, KeyError):
        await update.message.reply_text("Tarea no encontrada.")
        return

    if task.user_id != user.id:
        await update.message.reply_text("No tienes acceso a esa tarea.")
        return

    await update.message.reply_text(format_task(task), parse_mode=ParseMode.MARKDOWN)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config: Config = context.bot_data["config"]
    store: TaskStore = context.bot_data["store"]
    user = update.effective_user

    if not _is_authorized(user.id if user else None, config.telegram_allowed_users):
        await _reject_unauthorized(update)
        return

    description = update.message.text.strip()
    if not description:
        return

    task = await store.create(user.id, description)

    await update.message.reply_text(
        f"📋 Tarea #{task.id} recibida. Procesando...",
        parse_mode=ParseMode.MARKDOWN,
    )

    asyncio.create_task(
        _process_task(context.application, task.id, user.id, description)
    )


async def _process_task(
    app: Application, task_id: int, user_id: int, description: str
) -> None:
    store: TaskStore = app.bot_data["store"]
    agent: TaskAgent = app.bot_data["agent"]

    try:
        await store.update_status(task_id, TaskStatus.PROCESSING)
        result = await agent.process(description)
        task = await store.update_status(task_id, TaskStatus.COMPLETED, result)

        text = f"✅ *Tarea #{task.id} completada*\n\n{result}"
        await app.bot.send_message(
            chat_id=user_id,
            text=text[:4096],
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        logger.exception("Error procesando tarea %s", task_id)
        await store.update_status(
            task_id,
            TaskStatus.FAILED,
            "Error al procesar la tarea. Intenta de nuevo.",
        )
        await app.bot.send_message(
            chat_id=user_id,
            text=f"❌ Error al procesar la tarea #{task_id}. Intenta de nuevo.",
        )


async def _init_store(application: Application) -> None:
    store: TaskStore = application.bot_data["store"]
    await store.init()
    logger.info("Base de datos inicializada")


def build_application(config: Config, store: TaskStore, agent: TaskAgent) -> Application:
    app = (
        Application.builder()
        .token(config.telegram_bot_token)
        .post_init(_init_store)
        .build()
    )

    app.bot_data["config"] = config
    app.bot_data["store"] = store
    app.bot_data["agent"] = agent

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("tareas", list_tasks_command))
    app.add_handler(CommandHandler("tarea", task_detail_command))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    return app
