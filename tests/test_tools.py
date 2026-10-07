from assistant.config import Config
from assistant.tools import ToolExecutor, _is_allowed
from assistant.vault import VaultSearch
from pathlib import Path


def test_shell_whitelist() -> None:
    prefixes = frozenset(["ls", "git status"])
    assert _is_allowed("ls -la", prefixes)
    assert _is_allowed("git status", prefixes)
    assert not _is_allowed("rm -rf /", prefixes)


async def test_run_shell_rejects_disallowed() -> None:
    config = Config(
        telegram_bot_token="x",
        telegram_allowed_users=frozenset([1]),
        openai_api_key="x",
        openai_model="m",
        openai_base_url=None,
        database_path=Path("data/test.db"),
        vault_path=None,
        memory_max_messages=10,
        shell_allowed_prefixes=frozenset(["ls"]),
        rate_limit_per_minute=10,
        log_file=None,
        scheduler_interval_seconds=30,
    )
    tools = ToolExecutor(config, VaultSearch(None))
    result = await tools.execute("run_shell", '{"command": "rm -rf /"}')
    assert "no permitido" in result
