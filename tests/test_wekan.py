from unittest.mock import AsyncMock, patch

import pytest

from assistant.wekan import WekanClient, format_boards, format_cards


def test_format_boards_empty() -> None:
    assert format_boards([]) == "No hay tableros."


def test_format_cards() -> None:
    from assistant.wekan import WekanCard

    cards = [
        WekanCard(
            id="abc",
            title="Test",
            description="Desc",
            list_id="l1",
            list_title="Pendiente",
        )
    ]
    text = format_cards(cards)
    assert "Pendiente" in text
    assert "abc" in text


@pytest.mark.asyncio
async def test_list_boards() -> None:
    client = WekanClient(
        "http://test/api",
        "token",
        "author",
        "user1",
    )
    mock_data = [{"_id": "b1", "title": "assistant"}]
    with patch.object(client, "_request", AsyncMock(return_value=mock_data)), patch.object(
        client,
        "_workspace_context",
        AsyncMock(return_value=([], {})),
    ):
        boards = await client.list_boards()
    assert boards[0].title == "assistant"


@pytest.mark.asyncio
async def test_find_board_by_name() -> None:
    client = WekanClient("http://test/api", "token", "author", "user1")
    mock_boards = [
        {"_id": "b1", "title": "assistant"},
        {"_id": "b2", "title": "other"},
    ]
    with patch.object(client, "_request", AsyncMock(return_value=mock_boards)), patch.object(
        client,
        "_workspace_context",
        AsyncMock(return_value=([], {})),
    ):
        board = await client.find_board("assistant")
    assert board is not None
    assert board.id == "b1"


@pytest.mark.asyncio
async def test_list_boards_in_workspace() -> None:
    client = WekanClient("http://test/api", "token", "author", "user1")
    mock_boards = [
        {"_id": "b1", "title": "LCRC"},
        {"_id": "b2", "title": "assistant"},
    ]
    tree = [{"id": "ws1", "name": "LCRC", "children": []}]
    assignments = {"b1": "ws1"}

    with patch.object(client, "_request", AsyncMock(return_value=mock_boards)), patch.object(
        client,
        "_workspace_context",
        AsyncMock(return_value=(client._parse_workspace_tree(tree), assignments)),
    ):
        boards = await client.list_boards("LCRC")

    assert len(boards) == 1
    assert boards[0].title == "LCRC"


@pytest.mark.asyncio
async def test_list_cards_via_swimlanes() -> None:
    client = WekanClient("http://test/api", "token", "author", "user1")

    async def mock_request(method: str, path: str, json=None):
        if path.endswith("/lists"):
            return []
        if path.endswith("/swimlanes"):
            return [{"_id": "sl1", "title": "General"}]
        if "/swimlanes/sl1/cards" in path:
            return [{"_id": "c1", "title": "Tarea", "description": ""}]
        return {}

    with patch.object(client, "_request", side_effect=mock_request):
        cards = await client.list_cards("b1")

    assert len(cards) == 1
    assert cards[0].swimlane_title == "General"


@pytest.mark.asyncio
async def test_describe_workspace() -> None:
    client = WekanClient(
        "http://test/api",
        "token",
        "author",
        "user1",
        "http://wekan.test",
    )

    async def mock_request(method: str, path: str, json=None):
        if path == "/boards/b1":
            return {"slug": "lcrc"}
        return {}

    with patch.object(
        client,
        "find_workspace",
        AsyncMock(
            return_value=__import__(
                "assistant.wekan", fromlist=["WekanWorkspace"]
            ).WekanWorkspace(id="ws1", name="LCRC")
        ),
    ), patch.object(
        client,
        "list_boards",
        AsyncMock(
            return_value=[
                __import__("assistant.wekan", fromlist=["WekanBoard"]).WekanBoard(
                    id="b1", title="LCRC"
                )
            ]
        ),
    ), patch.object(client, "_request", side_effect=mock_request):
        text = await client.describe_workspace("LCRC")

    assert "LCRC" in text
    assert "Tableros" in text
    assert "wekan.test/b/b1/lcrc" in text
