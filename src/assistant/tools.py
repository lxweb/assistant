import asyncio
import json
from dataclasses import dataclass

from assistant.config import Config
from assistant.vault import VaultSearch
from assistant.wekan import WekanClient, format_boards, format_cards

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
            "name": "wekan_list_boards",
            "description": "Lista los tableros kanban disponibles en Wekan.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wekan_list_cards",
            "description": (
                "Lista cards de un tablero Wekan. "
                "Opcionalmente filtra por lista (Pendiente, En progreso, Terminada)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "board": {
                        "type": "string",
                        "description": "Nombre o id del tablero, ej: assistant",
                    },
                    "list": {
                        "type": "string",
                        "description": "Nombre de la lista (opcional)",
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
    "wekan_list_boards",
    "wekan_list_cards",
    "wekan_create_card",
    "wekan_move_card",
    "wekan_update_card",
}


@dataclass
class ToolExecutor:
    config: Config
    vault: VaultSearch
    wekan: WekanClient | None = None

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
        if not self.config.shell_allowed_prefixes:
            tools = [t for t in tools if t["function"]["name"] != "run_shell"]
        return tools

    async def execute(self, name: str, arguments: str) -> str:
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
            return await self._execute_wekan(name, args)

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

    async def _execute_wekan(self, name: str, args: dict) -> str:
        if not self.wekan or not self.wekan.available:
            return "Wekan no configurado."

        try:
            if name == "wekan_list_boards":
                boards = await self.wekan.list_boards()
                return format_boards(boards)

            board = await self.wekan.find_board(args.get("board", ""))
            if not board and name != "wekan_list_boards":
                return f"Tablero no encontrado: {args.get('board')}"

            if name == "wekan_list_cards":
                cards = await self.wekan.list_cards(board.id, args.get("list"))
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
