import asyncio
import json
from dataclasses import dataclass

from assistant.config import Config
from assistant.user_prefs import UserPrefsStore
from assistant.vault import VaultSearch
from assistant.wekan import (
    SECTION_PLURAL,
    SECTION_SINGULAR,
    WekanClient,
    format_boards,
    format_cards,
    format_sections,
    format_workspaces,
)

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "search_vault",
            "description": (
                "Busca notas en el KnowledgeVault (Obsidian) del usuario. "
                "Usar cuando la tarea requiera información documentada."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Términos de búsqueda",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_vault_note",
            "description": "Lee el contenido completo de una nota del vault por ruta relativa.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Ruta relativa, ej: Projects/assistant/Index.md",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wekan_list_workspaces",
            "description": (
                "Lista los workspaces (carpetas que agrupan tableros) en Wekan. "
                "Un workspace NO es un board. Ejemplo: LCRC, Servidor."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wekan_list_boards",
            "description": (
                "Lista los boards (tableros kanban). "
                "Opcionalmente filtra por workspace (carpeta). "
                "Para 'boards en LCRC' usar workspace='LCRC'. "
                f"No confundir workspace con board ni con {SECTION_SINGULAR}."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "workspace": {
                        "type": "string",
                        "description": (
                            "Nombre del workspace para filtrar, ej: LCRC. "
                            "Omitir para listar todos los boards."
                        ),
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wekan_list_secciones",
            "description": (
                f"Lista las {SECTION_PLURAL} (filas horizontales) de un board Wekan. "
                "Ej. en LCRC: General, 3TX, Captacion."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "board": {
                        "type": "string",
                        "description": "Nombre o id del board",
                    },
                },
                "required": ["board"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wekan_list_cards",
            "description": (
                "Lista cards de un board Wekan. "
                f"Filtra por lista (columna) o {SECTION_SINGULAR} (fila). "
                f"Algunos boards usan solo {SECTION_PLURAL} (ej. LCRC)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "board": {
                        "type": "string",
                        "description": "Nombre o id del board, ej: assistant o LCRC",
                    },
                    "list": {
                        "type": "string",
                        "description": "Nombre de lista/columna (opcional)",
                    },
                    "seccion": {
                        "type": "string",
                        "description": (
                            f"Nombre de la {SECTION_SINGULAR} / fila del tablero (opcional)"
                        ),
                    },
                },
                "required": ["board"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wekan_create_card",
            "description": "Crea una card en un tablero Wekan.",
            "parameters": {
                "type": "object",
                "properties": {
                    "board": {"type": "string", "description": "Nombre del tablero"},
                    "list": {
                        "type": "string",
                        "description": "Lista destino, ej: Pendiente",
                    },
                    "title": {"type": "string", "description": "Título de la card"},
                    "description": {
                        "type": "string",
                        "description": "Descripción (opcional)",
                    },
                },
                "required": ["board", "list", "title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wekan_move_card",
            "description": "Mueve una card a otra lista en Wekan.",
            "parameters": {
                "type": "object",
                "properties": {
                    "board": {"type": "string", "description": "Nombre del tablero"},
                    "card_id": {"type": "string", "description": "ID de la card"},
                    "to_list": {
                        "type": "string",
                        "description": "Lista destino, ej: Terminada",
                    },
                },
                "required": ["board", "card_id", "to_list"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wekan_update_card",
            "description": "Actualiza título o descripción de una card en Wekan.",
            "parameters": {
                "type": "object",
                "properties": {
                    "board": {"type": "string", "description": "Nombre del tablero"},
                    "card_id": {"type": "string", "description": "ID de la card"},
                    "title": {"type": "string", "description": "Nuevo título (opcional)"},
                    "description": {
                        "type": "string",
                        "description": "Nueva descripción (opcional)",
                    },
                },
                "required": ["board", "card_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wekan_create_workspace",
            "description": (
                "Crea un espacio de trabajo (workspace) en Wekan para agrupar tableros."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Nombre del espacio"},
                    "parent": {
                        "type": "string",
                        "description": "Espacio padre (opcional, para subcarpetas)",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wekan_update_workspace",
            "description": "Renombra un espacio de trabajo en Wekan.",
            "parameters": {
                "type": "object",
                "properties": {
                    "workspace": {
                        "type": "string",
                        "description": "Nombre o id del espacio actual",
                    },
                    "new_name": {"type": "string", "description": "Nuevo nombre"},
                },
                "required": ["workspace", "new_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wekan_delete_workspace",
            "description": (
                "Elimina (archiva) un espacio de trabajo. "
                "Los tableros quedan sin asignar; no se borran."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "workspace": {
                        "type": "string",
                        "description": "Nombre o id del espacio",
                    },
                },
                "required": ["workspace"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wekan_assign_board_to_workspace",
            "description": "Asigna un tablero a un espacio de trabajo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "board": {"type": "string", "description": "Nombre del tablero"},
                    "workspace": {
                        "type": "string",
                        "description": "Nombre del espacio de trabajo",
                    },
                },
                "required": ["board", "workspace"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wekan_unassign_board_from_workspace",
            "description": "Quita un tablero de su espacio (queda sin asignar).",
            "parameters": {
                "type": "object",
                "properties": {
                    "board": {"type": "string", "description": "Nombre del tablero"},
                },
                "required": ["board"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wekan_set_active_workspace",
            "description": (
                "Define el espacio de trabajo activo del usuario en el bot "
                "(contexto por defecto para tareas Wekan)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "workspace": {
                        "type": "string",
                        "description": "Nombre del espacio de trabajo",
                    },
                },
                "required": ["workspace"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": (
                "Ejecuta un comando shell permitido en el servidor. "
                "Solo comandos de la whitelist."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Comando a ejecutar",
                    }
                },
                "required": ["command"],
            },
        },
    },
]

WEKAN_TOOL_NAMES = {
    "wekan_list_workspaces",
    "wekan_list_boards",
    "wekan_list_secciones",
    "wekan_list_cards",
    "wekan_create_card",
    "wekan_move_card",
    "wekan_update_card",
    "wekan_create_workspace",
    "wekan_update_workspace",
    "wekan_delete_workspace",
    "wekan_assign_board_to_workspace",
    "wekan_unassign_board_from_workspace",
    "wekan_set_active_workspace",
}

WEKAN_WRITE_TOOL_NAMES = {
    "wekan_create_workspace",
    "wekan_update_workspace",
    "wekan_delete_workspace",
    "wekan_assign_board_to_workspace",
    "wekan_unassign_board_from_workspace",
    "wekan_set_active_workspace",
}


@dataclass
class ToolExecutor:
    config: Config
    vault: VaultSearch
    wekan: WekanClient | None = None
    prefs: UserPrefsStore | None = None

    def enabled_tools(self) -> list[dict]:
        tools = list(TOOL_DEFINITIONS)
        if not self.vault.available:
            tools = [
                t
                for t in tools
                if t["function"]["name"]
                not in ("search_vault", "read_vault_note")
            ]
        if not self.wekan or not self.wekan.available:
            tools = [t for t in tools if t["function"]["name"] not in WEKAN_TOOL_NAMES]
        elif not self.wekan.workspace_writes_enabled:
            tools = [
                t
                for t in tools
                if t["function"]["name"] not in WEKAN_WRITE_TOOL_NAMES
                or t["function"]["name"] == "wekan_set_active_workspace"
            ]
        if not self.config.shell_allowed_prefixes:
            tools = [t for t in tools if t["function"]["name"] != "run_shell"]
        return tools

    async def execute(
        self, name: str, arguments: str, user_id: int | None = None
    ) -> str:
        try:
            args = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError:
            return "Error: argumentos JSON inválidos"

        if name == "search_vault":
            query = args.get("query", "")
            hits = self.vault.search(query)
            if not hits:
                return "No se encontraron notas."
            lines = [f"- {h.title} ({h.path}): {h.snippet}" for h in hits]
            return "\n".join(lines)

        if name == "read_vault_note":
            path = args.get("path", "")
            content = self.vault.read(path)
            if content is None:
                return f"Nota no encontrada: {path}"
            return content

        if name in WEKAN_TOOL_NAMES:
            return await self._execute_wekan(name, args, user_id)

        if name == "run_shell":
            command = args.get("command", "").strip()
            if not command:
                return "Comando vacío."
            if not _is_allowed(command, self.config.shell_allowed_prefixes):
                return f"Comando no permitido: {command}"
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            output = stdout.decode(errors="replace").strip()
            err = stderr.decode(errors="replace").strip()
            if proc.returncode != 0:
                return f"Exit {proc.returncode}\n{err or output}"
            return output or "(sin salida)"

        return f"Herramienta desconocida: {name}"

    async def _execute_wekan(
        self, name: str, args: dict, user_id: int | None
    ) -> str:
        if not self.wekan or not self.wekan.available:
            return "Wekan no configurado."

        try:
            if name == "wekan_list_workspaces":
                workspaces = await self.wekan.list_workspaces()
                return format_workspaces(workspaces)

            if name == "wekan_list_boards":
                workspace = args.get("workspace")
                boards = await self.wekan.list_boards(workspace)
                return format_boards(boards, workspace_name=workspace)

            if name == "wekan_create_workspace":
                ws = await self.wekan.create_workspace(
                    args["name"], parent=args.get("parent")
                )
                return f"Espacio creado: {ws.name} (id: {ws.id})"

            if name == "wekan_update_workspace":
                ws = await self.wekan.update_workspace(
                    args["workspace"], new_name=args["new_name"]
                )
                return f"Espacio renombrado a: {ws.name} (id: {ws.id})"

            if name == "wekan_delete_workspace":
                deleted = await self.wekan.delete_workspace(args["workspace"])
                return f"Espacio eliminado: {deleted}. Sus tableros quedaron sin asignar."

            if name == "wekan_assign_board_to_workspace":
                return await self.wekan.assign_board_to_workspace(
                    args["board"], args["workspace"]
                )

            if name == "wekan_unassign_board_from_workspace":
                return await self.wekan.unassign_board_from_workspace(args["board"])

            if name == "wekan_set_active_workspace":
                if not self.prefs or user_id is None:
                    return "Preferencias de usuario no disponibles."
                ws = await self.wekan.find_workspace(args["workspace"])
                if not ws:
                    return f"Espacio no encontrado: {args.get('workspace')}"
                await self.prefs.set_active_workspace(user_id, ws.name)
                return f"Espacio de trabajo activo: {ws.name}"

            board = await self.wekan.find_board(args.get("board", ""))
            if not board:
                return f"Tablero no encontrado: {args.get('board')}"

            if name == "wekan_list_secciones":
                sections = await self.wekan.list_swimlanes(board.id)
                return format_sections(sections)

            if name == "wekan_list_cards":
                seccion = args.get("seccion") or args.get("swimlane")
                cards = await self.wekan.list_cards(
                    board.id,
                    list_name=args.get("list"),
                    swimlane_name=seccion,
                )
                return format_cards(cards)

            if name == "wekan_create_card":
                card = await self.wekan.create_card(
                    board.id,
                    args["list"],
                    args["title"],
                    args.get("description", ""),
                )
                return (
                    f"Card creada: {card.title} (id: {card.id}) "
                    f"en [{card.list_title}]"
                )

            if name == "wekan_move_card":
                card = await self.wekan.move_card(
                    board.id, args["card_id"], args["to_list"]
                )
                return f"Card movida a [{card.list_title}]: {card.title} (id: {card.id})"

            if name == "wekan_update_card":
                card = await self.wekan.update_card(
                    board.id,
                    args["card_id"],
                    title=args.get("title"),
                    description=args.get("description"),
                )
                return f"Card actualizada: {card.title} (id: {card.id})"

        except Exception as exc:
            return f"Error Wekan: {exc}"

        return "Operación Wekan no implementada."


def _is_allowed(command: str, prefixes: frozenset[str]) -> bool:
    return any(command.startswith(p) for p in prefixes)
