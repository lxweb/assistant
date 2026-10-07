import re
from dataclasses import dataclass
from pathlib import Path

from assistant.wekan import WekanClient, format_boards


@dataclass
class Project:
    name: str
    status: str
    summary: str
    wekan_board: str | None
    wekan_url: str | None


def list_vault_projects(vault_path: Path) -> list[Project]:
    projects_dir = vault_path / "Projects"
    if not projects_dir.is_dir():
        return []

    projects: list[Project] = []
    for index_file in sorted(projects_dir.glob("*/Index.md")):
        name = index_file.parent.name
        try:
            text = index_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        meta = _parse_frontmatter(text)
        if meta.get("type") not in (None, "project"):
            continue
        projects.append(
            Project(
                name=name,
                status=meta.get("status", "unknown"),
                summary=meta.get("summary", ""),
                wekan_board=meta.get("wekan_board"),
                wekan_url=meta.get("wekan_url"),
            )
        )
    return projects


async def list_projects(
    vault_path: Path | None, wekan: WekanClient | None
) -> str:
    if vault_path and vault_path.is_dir():
        projects = list_vault_projects(vault_path)
        if projects:
            return format_projects(projects)

    if wekan and wekan.available:
        boards = await wekan.list_boards()
        if boards:
            return "📁 *Tableros Wekan*\n\n" + format_boards(boards)

    return "No hay proyectos configurados (vault o Wekan no disponibles)."


def format_projects(projects: list[Project]) -> str:
    active = [p for p in projects if p.status == "active"]
    other = [p for p in projects if p.status != "active"]

    lines = [f"📁 *Proyectos* ({len(projects)} total, {len(active)} activos)\n"]
    lines.extend(_format_project_group("Activos", active))
    if other:
        lines.append("")
        lines.extend(_format_project_group("Otros", other))
    return "\n".join(lines)


def _format_project_group(title: str, projects: list[Project]) -> list[str]:
    if not projects:
        return []
    lines = [f"*{title}:*"]
    for p in sorted(projects, key=lambda x: x.name.lower()):
        summary = f"\n  _{p.summary[:100]}_" if p.summary else ""
        wekan = f"\n  [Wekan]({p.wekan_url})" if p.wekan_url else ""
        lines.append(f"• *{p.name}* — `{p.status}`{summary}{wekan}")
    return lines


def _parse_frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return {}
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.strip().strip('"')
        meta[key.strip()] = value
    return meta
