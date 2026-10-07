import logging

from openai import AsyncOpenAI

from assistant.config import Config
from assistant.memory import ConversationStore
from assistant.tools import ToolExecutor

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

No inventes datos. Si no puedes completar algo, explica por qué y qué necesitarías.\
"""

MAX_TOOL_ITERATIONS = 5


class TaskAgent:
    def __init__(
        self,
        config: Config,
        memory: ConversationStore,
        tools: ToolExecutor,
    ) -> None:
        kwargs: dict = {"api_key": config.openai_api_key}
        if config.openai_base_url:
            kwargs["base_url"] = config.openai_base_url
        self._client = AsyncOpenAI(**kwargs)
        self._model = config.openai_model
        self._config = config
        self._memory = memory
        self._tools = tools

    async def process(self, user_id: int, task_description: str) -> str:
        history = await self._memory.get_recent(
            user_id, self._config.memory_max_messages
        )
        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for msg in history:
            messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": task_description})

        tool_defs = self._tools.enabled_tools()
        result = await self._chat_with_tools(messages, tool_defs)

        await self._memory.add(user_id, "user", task_description)
        await self._memory.add(user_id, "assistant", result)
        return result

    async def _chat_with_tools(
        self, messages: list[dict], tool_defs: list[dict]
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
                    tc.function.name, tc.function.arguments
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
