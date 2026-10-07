import asyncio
import json
from dataclasses import dataclass

from assistant.config import Config
from assistant.vault import VaultSearch

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


@dataclass
class ToolExecutor:
    config: Config
    vault: VaultSearch

    def enabled_tools(self) -> list[dict]:
        tools = list(TOOL_DEFINITIONS)
        if not self.vault.available:
            tools = [t for t in tools if t["function"]["name"] != "search_vault"
                     and t["function"]["name"] != "read_vault_note"]
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


def _is_allowed(command: str, prefixes: frozenset[str]) -> bool:
    return any(command.startswith(p) for p in prefixes)
