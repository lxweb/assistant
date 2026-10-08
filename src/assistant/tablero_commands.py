from telegram import Update
from telegram.ext import ContextTypes

from assistant.user_prefs import UserPrefsStore
from assistant.utils import send_long_message
from assistant.wekan import WekanBoard, WekanClient, format_cards, format_sections

TABLERO_SUBCOMMANDS = frozenset({"ayuda", "help", "usar", "use", "secciones", "listas"})

TARJETAS_SUBCOMMANDS = frozenset({"ayuda", "help", "crear", "mover"})


async def _resolve_board(
    wekan: WekanClient,
    prefs: UserPrefsStore,
    user_id: int,
    args: list[str],
) -> tuple[WekanBoard | None, list[str]]:
    if not args:
        name = await prefs.get_active_board(user_id)
        if not name:
            return None, []
        return await wekan.find_board(name), []

    board = await wekan.find_board(args[0])
    if board:
        return board, args[1:]

    active = await prefs.get_active_board(user_id)
    if active:
        active_board = await wekan.find_board(active)
        if active_board:
            return active_board, args
    return None, args


def _parse_card_filter(rest: list[str]) -> tuple[str | None, str | None]:
    if not rest:
        return None, None
    if rest[0].lower() == "seccion" and len(rest) >= 2:
        return None, " ".join(rest[1:])
    if rest[0].lower() == "en" and len(rest) >= 2:
        return " ".join(rest[1:]), None
    return " ".join(rest), None


async def _reply_board_detail(
    update: Update,
    wekan: WekanClient,
    prefs: UserPrefsStore,
    user_id: int,
    board_name: str,
) -> None:
    board = await wekan.find_board(board_name)
    if not board:
        await update.message.reply_text(f"Tablero no encontrado: {board_name}")
        return
    await prefs.set_active_board(user_id, board.title)
    text = await wekan.describe_board(board.title)
    text += "\n\n_Tablero activo en el bot._"
    await send_long_message(
        update.get_bot(),
        update.effective_chat.id,
        text,
        parse_mode="Markdown",
    )


async def tableros_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    wekan: WekanClient | None = context.bot_data.get("wekan")
    prefs: UserPrefsStore = context.bot_data["prefs"]
    user = update.effective_user

    if not wekan or not wekan.available:
        await update.message.reply_text("Wekan no está configurado.")
        return

    workspace = await prefs.get_active_workspace(user.id)
    text = await wekan.list_boards_markdown(workspace)
    if workspace:
        text += f"\n\n_(Espacio activo: {workspace})_"
    await send_long_message(
        update.get_bot(),
        update.effective_chat.id,
        text,
        parse_mode="Markdown",
    )


async def tablero_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    wekan: WekanClient | None = context.bot_data.get("wekan")
    prefs: UserPrefsStore = context.bot_data["prefs"]
    user = update.effective_user

    if not wekan or not wekan.available:
        await update.message.reply_text("Wekan no está configurado.")
        return

    args = context.args or []
    if not args:
        active = await prefs.get_active_board(user.id)
        if active:
            await _reply_board_detail(update, wekan, prefs, user.id, active)
            return
        await update.message.reply_text(
            "Sin tablero activo. Usa /tablero assistant o /tableros."
        )
        return

    sub = args[0].lower()
    rest = args[1:]

    try:
        if sub in ("ayuda", "help"):
            await update.message.reply_text(TABLERO_HELP, parse_mode="Markdown")
            return

        if sub in ("usar", "use"):
            if not rest:
                await update.message.reply_text("Uso: /tablero usar <nombre>")
                return
            await _reply_board_detail(update, wekan, prefs, user.id, " ".join(rest))
            return

        if sub == "secciones":
            name = " ".join(rest) if rest else await prefs.get_active_board(user.id)
            if not name:
                await update.message.reply_text(
                    "Uso: /tablero secciones <tablero> o fija un tablero activo."
                )
                return
            target = await wekan.find_board(name)
            if not target:
                await update.message.reply_text("Tablero no encontrado.")
                return
            text = format_sections(await wekan.list_swimlanes(target.id))
            await update.message.reply_text(
                f"*{target.title}*\n{text}", parse_mode="Markdown"
            )
            return

        if sub == "listas":
            name = " ".join(rest) if rest else await prefs.get_active_board(user.id)
            if not name:
                await update.message.reply_text(
                    "Uso: /tablero listas <tablero> o fija un tablero activo."
                )
                return
            target = await wekan.find_board(name)
            if not target:
                await update.message.reply_text("Tablero no encontrado.")
                return
            lists = await wekan.list_lists(target.id)
            if not lists:
                await update.message.reply_text(
                    f"*{target.title}*: sin listas (puede usar solo secciones).",
                    parse_mode="Markdown",
                )
                return
            body = "\n".join(f"- {item.title} (id: {item.id})" for item in lists)
            await update.message.reply_text(
                f"*{target.title}* — listas:\n{body}",
                parse_mode="Markdown",
            )
            return

        if sub not in TABLERO_SUBCOMMANDS:
            name = " ".join(args)
            await _reply_board_detail(update, wekan, prefs, user.id, name)
            return

        await update.message.reply_text("Subcomando desconocido. /tablero ayuda")
    except ValueError as exc:
        await update.message.reply_text(str(exc))
    except Exception as exc:
        await update.message.reply_text(f"Error: {exc}")


TABLERO_HELP = """\
*Tableros Wekan*

/tableros — Tableros del espacio activo \\(o todos\\)
/tablero — Tablero activo \\(detalle\\)
/tablero \\<nombre\\> — Ver tablero y fijarlo como activo
/tablero secciones \\[tablero\\]
/tablero listas \\[tablero\\]

*Tareas kanban \\(Wekan\\)*

/tareas — Tareas del tablero activo
/tareas \\<tablero\\>
/tareas \\<tablero\\> Pendiente
/tareas \\<tablero\\> seccion Captacion
/tareas crear Pendiente Título de la tarea
/tareas crear \\<tablero\\> Pendiente Título
/tareas mover \\<id\\> Terminada

_/procesos_ = cola del asistente \\(mensajes procesados por IA, no Wekan\\)._\
"""


async def tareas_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    wekan: WekanClient | None = context.bot_data.get("wekan")
    prefs: UserPrefsStore = context.bot_data["prefs"]
    user = update.effective_user

    if not wekan or not wekan.available:
        await update.message.reply_text("Wekan no está configurado.")
        return

    args = context.args or []
    if not args:
        board, _ = await _resolve_board(wekan, prefs, user.id, [])
        if not board:
            await update.message.reply_text(
                "Sin tablero activo. Usa /tablero <nombre> primero."
            )
            return
        cards = await wekan.list_cards(board.id)
        header = f"*{board.title}* — tareas ({len(cards)}):\n\n"
        await send_long_message(
            update.get_bot(),
            update.effective_chat.id,
            header + format_cards(cards),
            parse_mode="Markdown",
        )
        return

    sub = args[0].lower()

    try:
        if sub in ("ayuda", "help"):
            await update.message.reply_text(TABLERO_HELP, parse_mode="Markdown")
            return

        if sub == "crear":
            rest = args[1:]
            if len(rest) < 2:
                await update.message.reply_text(
                    "Uso: /tareas crear <lista> <título>\n"
                    "     /tareas crear <tablero> <lista> <título>"
                )
                return
            maybe_board = await wekan.find_board(rest[0])
            if maybe_board and len(rest) >= 3:
                board = maybe_board
                list_name = rest[1]
                title = " ".join(rest[2:])
            else:
                board, _ = await _resolve_board(wekan, prefs, user.id, [])
                if not board:
                    await update.message.reply_text("Sin tablero activo.")
                    return
                list_name = rest[0]
                title = " ".join(rest[1:])
            card = await wekan.create_card(board.id, list_name, title)
            await update.message.reply_text(
                f"Tarea creada en *{board.title}* [{card.list_title}]:\n"
                f"{card.title}\n(id: `{card.id}`)",
                parse_mode="Markdown",
            )
            return

        if sub == "mover":
            if len(args) < 3:
                await update.message.reply_text(
                    "Uso: /tareas mover <id_tarea> <lista_destino>"
                )
                return
            card_id = args[1]
            to_list = " ".join(args[2:])
            board, _ = await _resolve_board(wekan, prefs, user.id, [])
            if not board:
                await update.message.reply_text("Sin tablero activo.")
                return
            card = await wekan.move_card(board.id, card_id, to_list)
            await update.message.reply_text(
                f"Movida a [{card.list_title}]: {card.title} (id: {card.id})"
            )
            return

        board, rest = await _resolve_board(wekan, prefs, user.id, args)
        if not board:
            await update.message.reply_text(
                f"Tablero no encontrado. Args: {' '.join(args)}"
            )
            return

        list_name, swimlane_name = _parse_card_filter(rest)
        cards = await wekan.list_cards(
            board.id,
            list_name=list_name,
            swimlane_name=swimlane_name,
        )
        filt = list_name or swimlane_name
        filt_line = f" (filtro: {filt})" if filt else ""
        header = f"*{board.title}*{filt_line} — {len(cards)} tarea(s):\n\n"
        await send_long_message(
            update.get_bot(),
            update.effective_chat.id,
            header + format_cards(cards),
            parse_mode="Markdown",
        )
    except ValueError as exc:
        await update.message.reply_text(str(exc))
    except Exception as exc:
        await update.message.reply_text(f"Error: {exc}")
