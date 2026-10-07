from openai import AsyncOpenAI

from assistant.config import Config

SYSTEM_PROMPT = """\
Eres un asistente personal útil y conciso. El usuario te asigna tareas a través de Telegram.

Tu rol:
- Analizar la tarea y responder de forma clara y accionable
- Si la tarea requiere información que no tienes, indicarlo y sugerir pasos
- Si la tarea es una pregunta, responder directamente
- Si la tarea implica planificación, dar un plan estructurado
- Responder siempre en el mismo idioma que el usuario
- Mantener respuestas concisas (Telegram tiene límite de mensajes)

No inventes datos. Si no puedes completar algo, explica por qué y qué necesitarías.\
"""


class TaskAgent:
    def __init__(self, config: Config) -> None:
        kwargs: dict = {"api_key": config.openai_api_key}
        if config.openai_base_url:
            kwargs["base_url"] = config.openai_base_url
        self._client = AsyncOpenAI(**kwargs)
        self._model = config.openai_model

    async def process(self, task_description: str) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": task_description},
            ],
            max_tokens=2000,
        )
        return response.choices[0].message.content or "Sin respuesta del modelo."
