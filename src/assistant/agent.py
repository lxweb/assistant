import logging

from openai import AsyncOpenAI

from assistant.config import Config
from assistant.memory import ConversationStore
from assistant.tools import ToolExecutor
from assistant.user_prefs import UserPrefsStore
from assistant.wekan import WekanClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
Eres un asistente personal útil y conciso. El usuario te asigna tareas a través de Telegram.

Tu rol:
- Analizar la tarea y responder de forma clara y accionable
- Usar Wekan para gestionar tareas kanban (listar, crear, mover, actualizar cards)
- Usar herramientas cuando necesites datos del vault, notas o comandos del servidor
- Si la tarea requiere información que no tienes, indicarlo y sugerir pasos
- Responder siempre en el mismo idioma que el usuario
- Mantener respuestas concisas (Telegram tiene límite de mensajes)

Wekan — jerarquía (no confundir términos; nunca digas "swimlane" al usuario):
- Workspace: carpeta que agrupa boards (ej. LCRC, Servidor). Tool: wekan_list_workspaces
- Board: tablero kanban con cards (ej. assistant, LCRC). Tool: wekan_list_boards(workspace=...)
- Sección: fila horizontal dentro de un board (ej. General, 3TX, Captacion). NO es un board
- List: columna kanban (ej. Pendiente, En progreso, Terminada)
- Card: tarea individual

Si preguntan "boards en el workspace LCRC", usar wekan_list_boards con workspace="LCRC".
Si preguntan secciones de un board, usar wekan_list_secciones.
Para cards de una sección, usar wekan_list_cards con seccion="...".

Espacios de trabajo: crear/renombrar/eliminar/asignar tableros con las tools wekan_*_workspace.
Trabaja preferentemente dentro del espacio de trabajo activo del usuario (si se indica abajo).

No inventes datos. Si no puedes completar algo, explica por qué y qué necesitarías.\
"""

MAX_TOOL_ITERATIONS = 5


class TaskAgent:
    def __init__(
        self,
        config: Config,
        memory: ConversationStore,
        tools: ToolExecutor,
        prefs: UserPrefsStore | None = None,
        wekan: WekanClient | None = None,
    ) -> None:
        kwargs: dict = {"api_key": config.openai_api_key}
        if config.openai_base_url:
            kwargs["base_url"] = config.openai_base_url
        self._client = AsyncOpenAI(**kwargs)
        self._model = config.openai_model
        self._config = config
        self._memory = memory
        self._tools = tools
        self._prefs = prefs
        self._wekan = wekan

    async def _system_prompt(self, user_id: int) -> str:
        prompt = SYSTEM_PROMPT
        if not self._prefs:
            return prompt
        active_ws = await self._prefs.get_active_workspace(user_id)
        active_board = await self._prefs.get_active_board(user_id)
        if not active_ws and not active_board:
            return prompt
        extra = ""
        if active_ws:
            extra += (
                f"\n\nEspacio de trabajo activo del usuario: {active_ws}\n"
                f"Al listar tableros en Wekan, usa workspace=\"{active_ws}\" salvo "
                "que el usuario pida otro explícitamente."
            )
        if active_board:
            extra += (
                f"\nTablero activo del usuario: {active_board}\n"
                f"Operaciones de tareas/listas en Wekan: board=\"{active_board}\" "
                "salvo que indique otro tablero."
            )
        if self._wekan and not self._wekan.workspace_writes_enabled:
            extra += (
                "\n(La escritura de espacios en Wekan requiere WEKAN_MONGO_URL; "
                "el espacio activo del bot sí está guardado.)"
            )
        return prompt + extra

    async def process(self, user_id: int, task_description: str) -> str:
        history = await self._memory.get_recent(
            user_id, self._config.memory_max_messages
        )
        messages: list[dict] = [
            {"role": "system", "content": await self._system_prompt(user_id)}
        ]
        for msg in history:
            messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": task_description})

        tool_defs = self._tools.enabled_tools()
        result = await self._chat_with_tools(messages, tool_defs, user_id)

        await self._memory.add(user_id, "user", task_description)
        await self._memory.add(user_id, "assistant", result)
        return result

    async def _chat_with_tools(
        self, messages: list[dict], tool_defs: list[dict], user_id: int
    ) -> str:
        for _ in range(MAX_TOOL_ITERATIONS):
            kwargs: dict = {
                "model": self._model,
                "messages": messages,
                "max_tokens": 2000,
            }
            if tool_defs:
                kwargs["tools"] = tool_defs

            try:
                response = await self._client.chat.completions.create(**kwargs)
            except Exception as exc:
                if tool_defs and "tool" in str(exc).lower():
                    logger.warning("Modelo sin soporte tools, fallback sin herramientas")
                    return await self._chat_plain(messages)
                raise

            choice = response.choices[0]
            msg = choice.message

            if not msg.tool_calls:
                return msg.content or "Sin respuesta del modelo."

            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                }
            )

            for tc in msg.tool_calls:
                tool_result = await self._tools.execute(
                    tc.function.name,
                    tc.function.arguments,
                    user_id=user_id,
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result,
                    }
                )

        return "Se alcanzó el límite de iteraciones de herramientas."

    async def _chat_plain(self, messages: list[dict]) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=2000,
        )
        return response.choices[0].message.content or "Sin respuesta del modelo."
