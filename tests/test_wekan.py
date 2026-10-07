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
    with patch.object(client, "_request", AsyncMock(return_value=mock_data)):
        boards = await client.list_boards()
    assert boards[0].title == "assistant"


@pytest.mark.asyncio
async def test_find_board_by_name() -> None:
    client = WekanClient("http://test/api", "token", "author", "user1")
    mock_boards = [
        {"_id": "b1", "title": "assistant"},
        {"_id": "b2", "title": "other"},
    ]
    with patch.object(client, "_request", AsyncMock(return_value=mock_boards)):
        board = await client.find_board("assistant")
    assert board is not None
    assert board.id == "b1"
