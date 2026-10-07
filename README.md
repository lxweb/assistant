# Assistant — Asistente personal via Telegram

Asistente al que puedes asignar tareas enviando mensajes por Telegram. Procesa cada tarea con un modelo de IA y te responde con el resultado.

## Requisitos

- Python 3.11+
- [Ollama](https://ollama.com) instalado y corriendo (backend local de IA)
- Un bot de Telegram (crear con [@BotFather](https://t.me/BotFather))

## Instalación

```bash
# Clonar / entrar al proyecto
cd assistant

# Crear entorno virtual
python -m venv .venv
source .venv/bin/activate

# Instalar dependencias
pip install -e .

# Configurar variables de entorno
cp .env.example .env
# Editar .env con tus valores
```

## Configuración

Edita el archivo `.env`:

| Variable | Descripción |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token del bot (de @BotFather) |
| `TELEGRAM_ALLOWED_USERS` | Tu ID de Telegram (separados por coma si son varios) |
| `OPENAI_API_KEY` | `ollama` para uso local |
| `OPENAI_BASE_URL` | `http://localhost:11434/v1` |
| `OPENAI_MODEL` | Modelo de Ollama (default: `llama3.1:8b-16k`) |

### Obtener tu ID de Telegram

1. Escribe a [@userinfobot](https://t.me/userinfobot) en Telegram
2. Te responderá con tu ID numérico
3. Ponlo en `TELEGRAM_ALLOWED_USERS`

### Crear el bot

1. Escribe a [@BotFather](https://t.me/BotFather)
2. Envía `/newbot`
3. Sigue las instrucciones y copia el token en `TELEGRAM_BOT_TOKEN`

## Uso

```bash
# Iniciar el bot
assistant
# o
python -m assistant.main
```

### Comandos de Telegram

| Comando | Descripción |
|---|---|
| `/start` | Iniciar el bot |
| `/help` | Ver ayuda |
| `/tareas` | Listar tus últimas tareas |
| `/tarea <id>` | Ver detalle de una tarea |

### Asignar tareas

Simplemente envía un mensaje de texto al bot:

```
Resume los puntos clave de machine learning
```

```
Escribe un email para pedir una reunión con el equipo de producto
```

```
Explícame qué es un webhook y cuándo usarlo
```

El bot confirmará la recepción, procesará la tarea con IA y te enviará el resultado.

## Modelos disponibles

El proyecto usa Ollama localmente. Modelos detectados en tu sistema:

| Modelo | Uso recomendado |
|---|---|
| `llama3.1:8b-16k` | Default — buen balance velocidad/calidad |
| `qwen3.5:0.8b` | Respuestas rápidas, tareas simples |
| `qwen3.5:27b-64k` | Máxima calidad, más lento |

Cambia `OPENAI_MODEL` en `.env` para usar otro modelo.

## Alternativa: OpenAI (cloud)

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
# Elimina o comenta OPENAI_BASE_URL
```

## Estructura del proyecto

```
assistant/
├── src/assistant/
│   ├── main.py      # Punto de entrada
│   ├── bot.py       # Handlers de Telegram
│   ├── agent.py     # Procesamiento con IA
│   ├── tasks.py     # Persistencia de tareas
│   └── config.py    # Configuración
├── data/            # Base de datos SQLite (auto-creada)
├── .env.example
└── pyproject.toml
```

## Seguridad

- Solo los usuarios listados en `TELEGRAM_ALLOWED_USERS` pueden interactuar con el bot
- No commitees el archivo `.env` (está en `.gitignore`)
- El bot token y la API key son secretos
