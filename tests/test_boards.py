from unittest.mock import AsyncMock, patch

import pytest

from assistant.wekan import WekanBoard, WekanClient, WekanList


@pytest.mark.asyncio
async def test_workspace_overview() -> None:
    client = WekanClient(
        "http://test/api",
        "token",
        "author",
        "user1",
        "http://wekan.test",
    )
    board = WekanBoard(id="b1", title="assistant")
    lst = WekanList(id="l1", title="Pendiente")

    async def mock_request(method: str, path: str, json=None):
        if path == "/boards/b1":
            return {"slug": "assistant"}
        if path.endswith("/cards"):
            return [{"_id": "c1"}]
        return {}

    with patch.object(
        client, "get_user", AsyncMock(return_value={"username": "lisandro"})
    ), patch.object(client, "list_boards", AsyncMock(return_value=[board])), patch.object(
        client, "list_lists", AsyncMock(return_value=[lst])
    ), patch.object(client, "_request", side_effect=mock_request):
        text = await client.workspace_overview()

    assert "lisandro" in text
    assert "assistant" in text
    assert "Pendiente (1)" in text
    assert "wekan.test/b/b1/assistant" in text
