import asyncio
import io
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
from assistant.speech import SpeechClient
from assistant.health import start_health_server
from assistant.espacio_commands import espacio_command, espacios_command
from assistant.tablero_commands import tablero_command, tableros_command, tareas_command
from assistant.user_prefs import UserPrefsStore
from assistant.wekan import WekanClient
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
/procesos — Cola de mensajes procesados por el asistente
/proceso \\<id\\> — Detalle de un proceso
/status — Estado del bot y servicios
/limpiar — Borrar memoria conversacional
/recordar \\<cuándo\\> \\<tarea\\> — Programar recordatorio
/recordatorios — Ver recordatorios pendientes
/boards — Workspaces y tableros Wekan (jerarquía)
/espacios — Listar espacios de trabajo
/espacio \\[nombre\\] — Detalle del espacio \\(tableros\\) y gestión
/tableros — Tableros del espacio activo
/tablero \\[nombre\\] — Detalle del tablero Wekan
/tareas — Tareas kanban \\(Wekan\\) del tablero activo

*Asignar tareas:*
Envía un mensaje de texto o una nota de voz con la tarea que quieres procesar.

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
        await update.message.reply_text("Uso: /proceso <id>")
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
    prefs: UserPrefsStore = context.bot_data["prefs"]
    scheduler: SchedulerStore = context.bot_data["scheduler"]

    ollama_ok = await _check_ollama(config)
    speech: SpeechClient = context.bot_data["speech"]
    stt_ok = await speech.check_stt()
    tts_ok = await speech.check_tts()
    wekan: WekanClient | None = context.bot_data.get("wekan")
    wekan_ok = (
        await wekan.check_connection()
        if wekan and wekan.available
        else None
    )
    counts = await store.count_by_status()
    user = update.effective_user
    recent = await memory.get_recent(user.id, 1)
    active_ws = await prefs.get_active_workspace(user.id)
    pending_reminders = await scheduler.list_by_user(user.id)

    wekan_line = (
        f"Wekan: {'✅ OK' if wekan_ok else '❌ no responde'}"
        if wekan_ok is not None
        else "Wekan: ❌ no configurado"
    )
    lines = [
        "*Estado del asistente*",
        f"Modelo: `{config.openai_model}`",
        f"Ollama: {'✅ OK' if ollama_ok else '❌ no responde'}",
        f"STT: {'✅ OK' if stt_ok else '❌ no configurado o no responde'}",
        f"TTS: {'✅ OK' if tts_ok else '❌ no configurado o no responde'}",
        f"Respuestas en voz: {'sí' if config.voice_replies else 'no'}",
        wekan_line,
        f"Vault: {'✅ ' + str(config.vault_path) if config.vault_path else '❌ no configurado'}",
        f"Tareas: {counts}",
        f"Memoria: {'activa' if recent else 'vacía'}",
        f"Espacio Wekan activo: {active_ws or '—'}",
        f"Tablero Wekan activo: {await prefs.get_active_board(user.id) or '—'}",
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


async def boards_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_access(update, context):
        return
    wekan: WekanClient | None = context.bot_data.get("wekan")
    if not wekan or not wekan.available:
        await update.message.reply_text("Wekan no está configurado.")
        return
    text = await wekan.workspace_overview()
    await send_long_message(
        update.get_bot(),
        update.effective_chat.id,
        text,
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


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_access(update, context):
        return
    speech: SpeechClient = context.bot_data["speech"]
    config: Config = context.bot_data["config"]
    user = update.effective_user
    message = update.message
    voice = message.voice or message.audio
    if not voice:
        return

    if not speech.stt_enabled:
        await message.reply_text(
            "Las notas de voz requieren STT. Configura STT_BASE_URL en el asistente "
            "y levanta el microservicio offline-ai-stt."
        )
        return

    await message.reply_chat_action("typing")
    try:
        tg_file = await voice.get_file()
        audio_bytes = await tg_file.download_as_bytearray()
        filename = "voice.ogg"
        if message.audio and message.audio.file_name:
            filename = message.audio.file_name
        text = await speech.transcribe(bytes(audio_bytes), filename=filename)
    except ValueError as exc:
        await message.reply_text(f"No pude entender el audio: {exc}")
        return
    except Exception:
        logger.exception("Error transcribiendo voz")
        await message.reply_text(
            "Error al transcribir el audio. Revisa que el servicio STT esté activo."
        )
        return

    store: TaskStore = context.bot_data["store"]
    task = await store.create(user.id, text)

    await message.reply_text(
        f"🎤 Transcripción: {text}\n\n📋 Tarea #{task.id} recibida. Procesando...",
    )

    reply_voice = config.voice_replies and speech.tts_enabled
    asyncio.create_task(
        _process_task(
            context.application,
            task.id,
            user.id,
            text,
            reply_with_voice=reply_voice,
        )
    )


async def process_user_message(app, user_id: int, description: str) -> None:
    store: TaskStore = app.bot_data["store"]
    task = await store.create(user_id, description)
    await _process_task(app, task.id, user_id, description)


async def _process_task(
    app,
    task_id: int,
    user_id: int,
    description: str,
    *,
    reply_with_voice: bool = False,
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
        if reply_with_voice:
            speech: SpeechClient = app.bot_data["speech"]
            try:
                snippet = result.strip()
                if len(snippet) > 1500:
                    snippet = snippet[:1497] + "..."
                wav = await speech.synthesize_wav(snippet)
                await app.bot.send_audio(
                    chat_id=user_id,
                    audio=io.BytesIO(wav),
                    filename="respuesta.wav",
                    caption=f"Tarea #{task.id} (voz)",
                )
            except Exception:
                logger.exception("Error generando respuesta en voz para tarea %s", task_id)
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
    wekan: WekanClient | None = application.bot_data.get("wekan")
    wekan_ok = await wekan.check_connection() if wekan and wekan.available else False
    healthy = ollama_ok and (wekan_ok or not (wekan and wekan.available))
    return {
        "status": "ok" if healthy else "degraded",
        "service": "assistant",
        "model": config.openai_model,
        "ollama": ollama_ok,
        "vault": config.vault_path is not None and config.vault_path.is_dir(),
        "wekan": wekan_ok if wekan and wekan.available else None,
        "tasks": await store.count_by_status(),
    }


async def _init_app(application: Application) -> None:
    store: TaskStore = application.bot_data["store"]
    memory: ConversationStore = application.bot_data["memory"]
    prefs: UserPrefsStore = application.bot_data["prefs"]
    scheduler: SchedulerStore = application.bot_data["scheduler"]
    config: Config = application.bot_data["config"]

    await store.init()
    await memory.init()
    await prefs.init()
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
    prefs: UserPrefsStore,
    scheduler: SchedulerStore,
    agent: TaskAgent,
    wekan: WekanClient | None = None,
    speech: SpeechClient | None = None,
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
    app.bot_data["prefs"] = prefs
    app.bot_data["scheduler"] = scheduler
    app.bot_data["agent"] = agent
    app.bot_data["wekan"] = wekan
    app.bot_data["speech"] = speech or SpeechClient(None, None)
    app.bot_data["rate_limiter"] = RateLimiter(config.rate_limit_per_minute)

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("procesos", list_tasks_command))
    app.add_handler(CommandHandler("proceso", task_detail_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("limpiar", clear_memory_command))
    app.add_handler(CommandHandler("recordar", remind_command))
    app.add_handler(CommandHandler("recordatorios", list_reminders_command))
    app.add_handler(CommandHandler("boards", boards_command))
    app.add_handler(CommandHandler("espacios", espacios_command))
    app.add_handler(CommandHandler("espacio", espacio_command))
    app.add_handler(CommandHandler("tableros", tableros_command))
    app.add_handler(CommandHandler("tablero", tablero_command))
    app.add_handler(CommandHandler("tareas", tareas_command))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    app.add_error_handler(_error_handler)

    return app
