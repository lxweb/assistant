# Assistant — Asistente personal via Telegram

Asistente al que puedes asignar tareas enviando mensajes por Telegram. Procesa cada tarea con Ollama local, recuerda el contexto, puede consultar tu KnowledgeVault y ejecutar comandos permitidos.

## Requisitos

- Python 3.11+
- [Ollama](https://ollama.com) instalado y corriendo
- Bot de Telegram ([@BotFather](https://t.me/BotFather))
- (Opcional) KnowledgeVault/Obsidian para herramientas de búsqueda

## Instalación

```bash
git clone https://github.com/lxweb/assistant.git
cd assistant
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
# Editar .env
```

## Configuración

| Variable | Descripción |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token del bot |
| `TELEGRAM_ALLOWED_USERS` | IDs de Telegram autorizados |
| `OPENAI_API_KEY` | `ollama` para uso local |
| `OPENAI_BASE_URL` | `http://localhost:11434/v1` |
| `OPENAI_MODEL` | Modelo Ollama (default: `llama3.1:8b-16k`) |
| `VAULT_PATH` | Ruta al vault Obsidian |
| `MEMORY_MAX_MESSAGES` | Mensajes de contexto por usuario |
| `SHELL_ALLOWED_PREFIXES` | Comandos shell permitidos |
| `RATE_LIMIT_PER_MINUTE` | Límite de mensajes por minuto |

## Docker (recomendado en servidor)

Ollama corre en el **host** (GPU). El bot corre en Docker y se conecta via `host.docker.internal`.

```bash
docker compose up -d --build
docker compose logs -f
curl http://127.0.0.1:10850/health
```

Imagen: **`assistant:latest`** (build local desde `Dockerfile`).

## Uso local (sin Docker)

```bash
assistant
```

### Comandos Telegram

| Comando | Descripción |
|---|---|
| `/start` | Iniciar |
| `/help` | Ayuda |
| `/tareas` | Listar tareas |
| `/tarea <id>` | Detalle de tarea |
| `/status` | Estado del bot y servicios |
| `/limpiar` | Borrar memoria conversacional |
| `/recordar 30m <tarea>` | Programar recordatorio |
| `/recordatorios` | Ver recordatorios pendientes |
| *texto* | Asignar tarea (puede usar Wekan, vault, etc.) |

### Wekan

`/boards` — muestra tu espacio de trabajo y tableros con conteo de cards por lista.

El asistente también puede gestionar Wekan por mensaje natural:

- Listar boards y cards
- Crear, mover y actualizar cards

Ejemplo: *"¿Qué hay pendiente en el board assistant?"*

## Systemd

**Docker (servidor):**
```bash
sudo cp deploy/assistant-docker.service /etc/systemd/system/
sudo systemctl enable --now assistant-docker
```

**Nativo (dev):**
```bash
./deploy/install-service.sh
systemctl --user start assistant
```

## Tests y CI

```bash
pip install -e ".[dev]"
pytest
```

GitHub Actions ejecuta tests en cada push a `main`.

## Estructura

```
assistant/
├── src/assistant/
│   ├── main.py        # Entry point
│   ├── bot.py         # Handlers Telegram
│   ├── agent.py       # Agente con memoria + tools
│   ├── tasks.py       # Tareas SQLite
│   ├── memory.py      # Memoria conversacional
│   ├── scheduler.py   # Recordatorios
│   ├── vault.py       # Búsqueda KnowledgeVault
│   ├── tools.py       # Herramientas (vault, shell)
│   └── config.py
├── deploy/            # Systemd unit
├── tests/
└── data/              # SQLite (gitignored)
```

## Documentación

Inventario completo en KnowledgeVault: `Projects/assistant/`

Tablero Wekan: http://wekan.home.lan/b/dM5RW7up2ab94nH4d/assistant

## Seguridad

- Solo usuarios en `TELEGRAM_ALLOWED_USERS`
- Shell restringido por whitelist de prefijos
- `.env` nunca se commitea
