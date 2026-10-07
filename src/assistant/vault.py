from dataclasses import dataclass
from pathlib import Path


@dataclass
class VaultHit:
    path: str
    title: str
    snippet: str


class VaultSearch:
    def __init__(self, vault_path: Path | None) -> None:
        self._vault_path = vault_path

    @property
    def available(self) -> bool:
        return self._vault_path is not None and self._vault_path.is_dir()

    def search(self, query: str, limit: int = 5) -> list[VaultHit]:
        if not self.available:
            return []

        terms = [t.lower() for t in query.split() if len(t) > 2]
        if not terms:
            return []

        hits: list[tuple[int, VaultHit]] = []
        for md_file in self._vault_path.rglob("*.md"):
            if ".obsidian" in md_file.parts:
                continue
            try:
                text = md_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            lower = text.lower()
            score = sum(lower.count(term) for term in terms)
            if score == 0:
                continue

            rel = md_file.relative_to(self._vault_path).as_posix()
            title = _extract_title(text) or md_file.stem
            snippet = _extract_snippet(text, terms)
            hits.append((score, VaultHit(path=rel, title=title, snippet=snippet)))

        hits.sort(key=lambda h: h[0], reverse=True)
        return [h[1] for h in hits[:limit]]

    def read(self, note_path: str) -> str | None:
        if not self.available:
            return None
        target = (self._vault_path / note_path).resolve()
        if not str(target).startswith(str(self._vault_path.resolve())):
            return None
        if not target.is_file():
            return None
        try:
            return target.read_text(encoding="utf-8", errors="replace")[:8000]
        except OSError:
            return None


def _extract_title(text: str) -> str | None:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


def _extract_snippet(text: str, terms: list[str], window: int = 120) -> str:
    lower = text.lower()
    pos = min((lower.find(t) for t in terms if t in lower), default=-1)
    if pos < 0:
        return text[:window].replace("\n", " ")
    start = max(0, pos - 40)
    end = min(len(text), pos + window)
    return text[start:end].replace("\n", " ").strip()
