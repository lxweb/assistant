import asyncio
import logging
from datetime import datetime, timezone

import httpx
from telegram import Update
from telegram.constants import ParseMode
from telegram.error import Conflict
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from assistant.agent import TaskAgent
from assistant.config import Config
from assistant.health import start_health_server
from assistant.memory import ConversationStore
from assistant.scheduler import SchedulerStore, parse_schedule_args, scheduler_loop
from assistant.tasks import (
    TaskStatus,
    TaskStore,
    format_task,
    format_task_list,
)
from assistant.utils import RateLimiter, send_long_message

logger = logging.getLogger(__name__)

HELP_TEXT = """\
*Comandos disponibles:*

/start — Iniciar el bot
/help — Mostrar esta ayuda
/tareas — Ver tus últimas tareas
/tarea \\<id\\> — Ver detalle de una tarea
/status — Estado del bot y servicios
/limpiar — Borrar memoria conversacional
/recordar \\<cuándo\\> \\<tarea\\> — Programar recordatorio
/recordatorios — Ver recordatorios pendientes

*Asignar tareas:*
Envía un mensaje de texto con la tarea que quieres procesar.

*Recordatorios:*
/recordar 30m Revisar el deploy
/recordar 2h Llamar al cliente
/recordar 2026\\-10\\-08T10:00 Reunión

El asistente usa memoria, Ollama y herramientas \\(vault, shell\\)\\.\
"""


def _is_authorized(user_id: int | None, allowed: frozenset[int]) -> bool:
    return user_id is not None and user_id in allowed


async def _reject_unauthorized(update: Update) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(
            "No tienes permiso para usar este bot."
        )


async def _check_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    config: Config = context.bot_data["config"]
    limiter: RateLimiter = context.bot_data["rate_limiter"]
    user = update.effective_user
    if not _is_authorized(user.id if user else None, config.telegram_allowed_users):
        await _reject_unauthorized(update)
        return False
    if not limiter.allow(user.id):
        await update.message.reply_text(
            "Demasiados mensajes. Espera un momento e intenta de nuevo."
        )
        return False
    return True


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_access(update, context):
        return
    user = update.effective_user
    await update.message.reply_text(
        f"Hola {user.first_name}! 👋\n\n"
        "Soy tu asistente personal. Envíame una tarea por mensaje "
        "y la procesaré por ti.\n\n"
        "Usa /help para ver los comandos disponibles.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_access(update, context):
        return
    await update.message.reply_text(HELP_TEXT, parse_mode=ParseMode.MARKDOWN_V2)


async def list_tasks_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not await _check_access(update, context):
        return
    store: TaskStore = context.bot_data["store"]
    user = update.effective_user
    tasks = await store.list_by_user(user.id)
    await update.message.reply_text(
        format_task_list(tasks), parse_mode=ParseMode.MARKDOWN
    )


async def task_detail_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not await _check_access(update, context):
        return
    store: TaskStore = context.bot_data["store"]
    user = update.effective_user

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


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_access(update, context):
        return
    config: Config = context.bot_data["config"]
    store: TaskStore = context.bot_data["store"]
    memory: ConversationStore = context.bot_data["memory"]
    scheduler: SchedulerStore = context.bot_data["scheduler"]

    ollama_ok = await _check_ollama(config)
    counts = await store.count_by_status()
    user = update.effective_user
    recent = await memory.get_recent(user.id, 1)
    pending_reminders = await scheduler.list_by_user(user.id)

    lines = [
        "*Estado del asistente*",
        f"Modelo: `{config.openai_model}`",
        f"Ollama: {'✅ OK' if ollama_ok else '❌ no responde'}",
        f"Vault: {'✅ ' + str(config.vault_path) if config.vault_path else '❌ no configurado'}",
        f"Tareas: {counts}",
        f"Memoria: {'activa' if recent else 'vacía'}",
        f"Recordatorios pendientes: {len(pending_reminders)}",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def clear_memory_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not await _check_access(update, context):
        return
    memory: ConversationStore = context.bot_data["memory"]
    user = update.effective_user
    deleted = await memory.clear(user.id)
    await update.message.reply_text(
        f"Memoria borrada ({deleted} mensajes eliminados)."
    )


async def remind_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_access(update, context):
        return
    scheduler: SchedulerStore = context.bot_data["scheduler"]
    user = update.effective_user

    parsed = parse_schedule_args(context.args)
    if not parsed:
        await update.message.reply_text(
            "Uso: /recordar <cuándo> <tarea>\n"
            "Ej: /recordar 30m Revisar logs\n"
            "Ej: /recordar 2026-10-08T10:00 Reunión"
        )
        return

    run_at, description = parsed
    item = await scheduler.schedule(user.id, description, run_at)
    await update.message.reply_text(
        f"⏰ Recordatorio #{item.id} programado para {run_at.isoformat()}\n"
        f"_{description}_",
        parse_mode=ParseMode.MARKDOWN,
    )


async def list_reminders_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not await _check_access(update, context):
        return
    scheduler: SchedulerStore = context.bot_data["scheduler"]
    user = update.effective_user
    items = await scheduler.list_by_user(user.id)
    if not items:
        await update.message.reply_text("No hay recordatorios pendientes.")
        return
    lines = []
    for item in items:
        lines.append(f"#{item.id} — {item.run_at}\n_{item.description}_")
    await update.message.reply_text("\n\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_access(update, context):
        return
    user = update.effective_user
    description = update.message.text.strip()
    if not description:
        return

    store: TaskStore = context.bot_data["store"]
    task = await store.create(user.id, description)

    await update.message.reply_text(
        f"📋 Tarea #{task.id} recibida. Procesando...",
        parse_mode=ParseMode.MARKDOWN,
    )

    asyncio.create_task(
        _process_task(context.application, task.id, user.id, description)
    )


async def process_user_message(app, user_id: int, description: str) -> None:
    store: TaskStore = app.bot_data["store"]
    task = await store.create(user_id, description)
    await _process_task(app, task.id, user_id, description)


async def _process_task(
    app, task_id: int, user_id: int, description: str
) -> None:
    store: TaskStore = app.bot_data["store"]
    agent: TaskAgent = app.bot_data["agent"]

    try:
        await store.update_status(task_id, TaskStatus.PROCESSING)
        result = await agent.process(user_id, description)
        task = await store.update_status(task_id, TaskStatus.COMPLETED, result)

        text = f"✅ *Tarea #{task.id} completada*\n\n{result}"
        await send_long_message(
            app.bot, user_id, text, parse_mode=ParseMode.MARKDOWN
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


async def _check_ollama(config: Config) -> bool:
    if not config.openai_base_url:
        return False
    try:
        base = config.openai_base_url.rstrip("/").removesuffix("/v1")
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"{base}/api/tags")
            return resp.status_code == 200
    except Exception:
        return False


async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if isinstance(context.error, Conflict):
        logger.warning(
            "Conflict de polling: otra instancia del bot está activa. "
            "Detén duplicados con: pkill -f 'assistant$'"
        )
        return
    logger.exception("Error no manejado", exc_info=context.error)


async def _health_status(application: Application) -> dict:
    config: Config = application.bot_data["config"]
    store: TaskStore = application.bot_data["store"]
    ollama_ok = await _check_ollama(config)
    return {
        "status": "ok" if ollama_ok else "degraded",
        "service": "assistant",
        "model": config.openai_model,
        "ollama": ollama_ok,
        "vault": config.vault_path is not None and config.vault_path.is_dir(),
        "tasks": await store.count_by_status(),
    }


async def _init_app(application: Application) -> None:
    store: TaskStore = application.bot_data["store"]
    memory: ConversationStore = application.bot_data["memory"]
    scheduler: SchedulerStore = application.bot_data["scheduler"]
    config: Config = application.bot_data["config"]

    await store.init()
    await memory.init()
    await scheduler.init()

    recovered = await store.recover_stuck()
    if recovered:
        logger.info("Recuperadas %d tareas colgadas en processing", recovered)

    application.bot_data["process_user_message"] = process_user_message

    asyncio.create_task(
        scheduler_loop(application, config.scheduler_interval_seconds)
    )

    async def status_fn() -> dict:
        return await _health_status(application)

    await start_health_server(config.health_host, config.health_port, status_fn)
    logger.info("Base de datos, scheduler y health server inicializados")


def build_application(
    config: Config,
    store: TaskStore,
    memory: ConversationStore,
    scheduler: SchedulerStore,
    agent: TaskAgent,
) -> Application:
    app = (
        Application.builder()
        .token(config.telegram_bot_token)
        .post_init(_init_app)
        .build()
    )

    app.bot_data["config"] = config
    app.bot_data["store"] = store
    app.bot_data["memory"] = memory
    app.bot_data["scheduler"] = scheduler
    app.bot_data["agent"] = agent
    app.bot_data["rate_limiter"] = RateLimiter(config.rate_limit_per_minute)

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("tareas", list_tasks_command))
    app.add_handler(CommandHandler("tarea", task_detail_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("limpiar", clear_memory_command))
    app.add_handler(CommandHandler("recordar", remind_command))
    app.add_handler(CommandHandler("recordatorios", list_reminders_command))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    app.add_error_handler(_error_handler)

    return app
