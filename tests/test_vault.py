from pathlib import Path

from assistant.vault import VaultSearch


def test_vault_search_finds_content(tmp_path: Path) -> None:
    note = tmp_path / "Projects" / "demo" / "Index.md"
    note.parent.mkdir(parents=True)
    note.write_text("# Demo\n\nTelegram assistant con Ollama local.\n")

    vault = VaultSearch(tmp_path)
    hits = vault.search("Telegram Ollama")

    assert len(hits) == 1
    assert hits[0].title == "Demo"
    assert "Telegram" in hits[0].snippet


def test_vault_read_blocks_traversal(tmp_path: Path) -> None:
    vault = VaultSearch(tmp_path)
    assert vault.read("../../etc/passwd") is None
