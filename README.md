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

## Uso

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
| *texto* | Asignar tarea |

## Systemd

```bash
./deploy/install-service.sh
systemctl --user start assistant
journalctl --user -u assistant -f
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
