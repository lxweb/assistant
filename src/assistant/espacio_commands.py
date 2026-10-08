from telegram import Update
from telegram.ext import ContextTypes

from assistant.user_prefs import UserPrefsStore
from assistant.utils import send_long_message
from assistant.wekan import WekanClient, format_workspaces

ESPACIO_SUBCOMMANDS = frozenset(
    {
        "ayuda",
        "help",
        "usar",
        "use",
        "activar",
        "crear",
        "renombrar",
        "rename",
        "archivar",
        "eliminar",
        "delete",
        "asignar",
        "quitar",
    }
)

ESPACIO_HELP = """\
*Espacios de trabajo Wekan*

/espacios — Listar espacios
/espacio — Espacio activo \\(detalle y tableros\\)
/espacio \\<nombre\\> — Ver espacio, tableros y fijarlo como activo
/espacio usar \\<nombre\\> — Igual que /espacio \\<nombre\\>
/espacio crear \\<nombre\\> — Crear espacio
/espacio crear \\<nombre\\> en \\<padre\\> — Subespacio
/espacio renombrar \\<actual\\> \\<nuevo\\>
/espacio archivar \\<nombre\\> — Elimina carpeta \\(tableros sin asignar\\)
/espacio asignar \\<tablero\\> \\<espacio\\>
/espacio quitar \\<tablero\\>

El espacio activo orienta al asistente en tareas Wekan por mensaje.\
"""


async def _reply_workspace_detail(
    update: Update,
    wekan: WekanClient,
    prefs: UserPrefsStore,
    user_id: int,
    workspace_name: str,
) -> None:
    ws = await wekan.find_workspace(workspace_name)
    if not ws:
        await update.message.reply_text(
            f"Espacio no encontrado: {workspace_name}"
        )
        return
    await prefs.set_active_workspace(user_id, ws.name)
    text = await wekan.describe_workspace(ws.name)
    text += "\n\n_Espacio activo en el bot._"
    await send_long_message(
        update.get_bot(),
        update.effective_chat.id,
        text,
        parse_mode="Markdown",
    )


async def espacios_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    wekan: WekanClient | None = context.bot_data.get("wekan")
    if not wekan or not wekan.available:
        await update.message.reply_text("Wekan no está configurado.")
        return
    workspaces = await wekan.list_workspaces()
    text = format_workspaces(workspaces)
    if not wekan.workspace_writes_enabled:
        text += (
            "\n\n(Lectura vía API. Para crear/modificar espacios configura "
            "WEKAN_MONGO_URL en el bot.)"
        )
    await update.message.reply_text(text)


async def espacio_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    wekan: WekanClient | None = context.bot_data.get("wekan")
    prefs: UserPrefsStore = context.bot_data["prefs"]
    user = update.effective_user

    if not wekan or not wekan.available:
        await update.message.reply_text("Wekan no está configurado.")
        return

    args = context.args or []
    if not args:
        active = await prefs.get_active_workspace(user.id)
        if active:
            await _reply_workspace_detail(update, wekan, prefs, user.id, active)
            return
        write = "✅" if wekan.workspace_writes_enabled else "❌ (falta WEKAN_MONGO_URL)"
        lines = [
            "*Sin espacio activo*",
            f"*Escritura Wekan:* {write}",
            "",
            "Usa /espacio LCRC o /espacio ayuda.",
        ]
        await send_long_message(
            update.get_bot(),
            update.effective_chat.id,
            "\n".join(lines),
            parse_mode="Markdown",
        )
        return

    sub = args[0].lower()
    rest = args[1:]

    try:
        if sub in ("ayuda", "help"):
            await update.message.reply_text(ESPACIO_HELP, parse_mode="MarkdownV2")
            return

        if sub in ("usar", "use", "activar"):
            if not rest:
                await update.message.reply_text("Uso: /espacio usar <nombre>")
                return
            name = " ".join(rest)
            await _reply_workspace_detail(update, wekan, prefs, user.id, name)
            return

        if sub == "crear":
            if not rest:
                await update.message.reply_text(
                    "Uso: /espacio crear <nombre>\n"
                    "     /espacio crear <nombre> en <padre>"
                )
                return
            parent = None
            if " en " in " ".join(rest):
                parts = " ".join(rest).split(" en ", 1)
                name, parent = parts[0].strip(), parts[1].strip()
            else:
                name = " ".join(rest).strip()
            ws = await wekan.create_workspace(name, parent=parent)
            await _reply_workspace_detail(update, wekan, prefs, user.id, ws.name)
            return

        if sub in ("renombrar", "rename"):
            if len(rest) < 2:
                await update.message.reply_text(
                    "Uso: /espacio renombrar <actual> <nuevo>"
                )
                return
            current, new_name = rest[0], " ".join(rest[1:])
            ws = await wekan.update_workspace(current, new_name=new_name)
            active = await prefs.get_active_workspace(user.id)
            if active and active.lower() == current.lower():
                await prefs.set_active_workspace(user.id, ws.name)
            await update.message.reply_text(f"Espacio renombrado a: {ws.name}")
            return

        if sub in ("archivar", "eliminar", "delete"):
            if not rest:
                await update.message.reply_text("Uso: /espacio archivar <nombre>")
                return
            name = " ".join(rest)
            deleted = await wekan.delete_workspace(name)
            active = await prefs.get_active_workspace(user.id)
            if active and active.lower() == deleted.lower():
                await prefs.delete(user.id, "active_workspace")
            await update.message.reply_text(
                f"Espacio eliminado: {deleted}\n"
                "Los tableros que tenía quedaron sin asignar."
            )
            return

        if sub == "asignar":
            if len(rest) < 2:
                await update.message.reply_text(
                    "Uso: /espacio asignar <tablero> <espacio>"
                )
                return
            board_name = rest[0]
            workspace_name = " ".join(rest[1:])
            msg = await wekan.assign_board_to_workspace(board_name, workspace_name)
            await update.message.reply_text(msg)
            return

        if sub == "quitar":
            if not rest:
                await update.message.reply_text("Uso: /espacio quitar <tablero>")
                return
            board_name = " ".join(rest)
            msg = await wekan.unassign_board_from_workspace(board_name)
            await update.message.reply_text(msg)
            return

        if sub not in ESPACIO_SUBCOMMANDS:
            name = " ".join(args)
            await _reply_workspace_detail(update, wekan, prefs, user.id, name)
            return

        await update.message.reply_text(
            "Subcomando desconocido. Prueba /espacio ayuda."
        )
    except ValueError as exc:
        await update.message.reply_text(str(exc))
    except Exception as exc:
        await update.message.reply_text(f"Error: {exc}")
