from assistant.wekan import (
    _insert_workspace_raw,
    _remove_workspace_from_raw,
    _update_workspace_raw,
)


def test_create_child_workspace() -> None:
    tree = [{"id": "root1", "name": "Root", "children": []}]
    node = {"id": "child1", "name": "Hijo", "children": []}
    tree = _insert_workspace_raw(tree, "root1", node)
    assert tree[0]["children"][0]["name"] == "Hijo"


def test_rename_and_delete_workspace() -> None:
    tree = [
        {
            "id": "a",
            "name": "A",
            "children": [{"id": "b", "name": "B", "children": []}],
        }
    ]
    tree = _update_workspace_raw(tree, "b", name="Beta")
    assert tree[0]["children"][0]["name"] == "Beta"

    tree, removed = _remove_workspace_from_raw(tree, "a")
    assert removed == ["a", "b"]
    assert tree == []
