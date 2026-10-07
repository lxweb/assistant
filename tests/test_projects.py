from pathlib import Path

from assistant.projects import _parse_frontmatter, list_vault_projects


def test_parse_frontmatter() -> None:
    text = "---\ntype: project\nstatus: active\nsummary: Demo project\n---\n# Title"
    meta = _parse_frontmatter(text)
    assert meta["status"] == "active"
    assert meta["summary"] == "Demo project"


def test_list_vault_projects(tmp_path: Path) -> None:
    project_dir = tmp_path / "Projects" / "demo"
    project_dir.mkdir(parents=True)
    (project_dir / "Index.md").write_text(
        "---\ntype: project\nstatus: active\nsummary: A demo\nwekan_url: http://x\n---\n# demo\n"
    )
    projects = list_vault_projects(tmp_path)
    assert len(projects) == 1
    assert projects[0].name == "demo"
    assert projects[0].status == "active"
