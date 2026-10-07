import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


@dataclass
class WekanBoard:
    id: str
    title: str


@dataclass
class WekanList:
    id: str
    title: str


@dataclass
class WekanCard:
    id: str
    title: str
    description: str
    list_id: str
    list_title: str


class WekanClient:
    def __init__(self, api_url: str, token: str, author_id: str, user_id: str) -> None:
        self._api_url = api_url.rstrip("/")
        self._token = token
        self._author_id = author_id
        self._user_id = user_id

    @property
    def available(self) -> bool:
        return bool(self._api_url and self._token and self._author_id)

    async def _request(
        self,
        method: str,
        path: str,
        json: dict | None = None,
    ) -> dict | list:
        url = f"{self._api_url}{path}"
        headers = {"Authorization": f"Bearer {self._token}"}
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.request(method, url, headers=headers, json=json)
            response.raise_for_status()
            if not response.content:
                return {}
            return response.json()

    async def check_connection(self) -> bool:
        try:
            await self._request("GET", f"/users/{self._user_id}/boards")
            return True
        except Exception:
            logger.exception("Wekan no responde")
            return False

    async def list_boards(self) -> list[WekanBoard]:
        data = await self._request("GET", f"/users/{self._user_id}/boards")
        return [WekanBoard(id=b["_id"], title=b["title"]) for b in data]

    async def find_board(self, name: str) -> WekanBoard | None:
        name_lower = name.lower().strip()
        for board in await self.list_boards():
            if board.id == name or board.title.lower() == name_lower:
                return board
        for board in await self.list_boards():
            if name_lower in board.title.lower():
                return board
        return None

    async def list_lists(self, board_id: str) -> list[WekanList]:
        data = await self._request("GET", f"/boards/{board_id}/lists")
        return [WekanList(id=item["_id"], title=item["title"]) for item in data]

    async def find_list(self, board_id: str, name: str) -> WekanList | None:
        name_lower = name.lower().strip()
        for item in await self.list_lists(board_id):
            if item.id == name or item.title.lower() == name_lower:
                return item
        for item in await self.list_lists(board_id):
            if name_lower in item.title.lower():
                return item
        return None

    async def list_cards(
        self, board_id: str, list_name: str | None = None
    ) -> list[WekanCard]:
        lists = await self.list_lists(board_id)
        if list_name:
            found = await self.find_list(board_id, list_name)
            lists = [found] if found else []

        cards: list[WekanCard] = []
        for lst in lists:
            data = await self._request(
                "GET", f"/boards/{board_id}/lists/{lst.id}/cards"
            )
            for c in data:
                cards.append(
                    WekanCard(
                        id=c["_id"],
                        title=c.get("title", ""),
                        description=c.get("description", "") or "",
                        list_id=lst.id,
                        list_title=lst.title,
                    )
                )
        return cards

    async def find_card(self, board_id: str, card_id: str) -> WekanCard | None:
        for card in await self.list_cards(board_id):
            if card.id == card_id:
                return card
        return None

    async def _default_swimlane(self, board_id: str) -> str:
        data = await self._request("GET", f"/boards/{board_id}/swimlanes")
        if data:
            return data[0]["_id"]
        board = await self._request("GET", f"/boards/{board_id}")
        swimlane = board.get("defaultSwimlaneId")
        if swimlane:
            return swimlane
        raise ValueError("No se encontró swimlane en el tablero")

    async def create_card(
        self,
        board_id: str,
        list_name: str,
        title: str,
        description: str = "",
    ) -> WekanCard:
        lst = await self.find_list(board_id, list_name)
        if not lst:
            raise ValueError(f"Lista no encontrada: {list_name}")

        swimlane_id = await self._default_swimlane(board_id)
        payload = {
            "title": title,
            "description": description,
            "swimlaneId": swimlane_id,
            "authorId": self._author_id,
        }
        result = await self._request(
            "POST",
            f"/boards/{board_id}/lists/{lst.id}/cards",
            json=payload,
        )
        return WekanCard(
            id=result["_id"],
            title=title,
            description=description,
            list_id=lst.id,
            list_title=lst.title,
        )

    async def move_card(
        self, board_id: str, card_id: str, to_list_name: str
    ) -> WekanCard:
        card = await self.find_card(board_id, card_id)
        if not card:
            raise ValueError(f"Card no encontrada: {card_id}")

        target = await self.find_list(board_id, to_list_name)
        if not target:
            raise ValueError(f"Lista destino no encontrada: {to_list_name}")

        await self._request(
            "PUT",
            f"/boards/{board_id}/lists/{card.list_id}/cards/{card_id}",
            json={"id": card_id, "listId": target.id, "boardId": board_id},
        )
        card.list_id = target.id
        card.list_title = target.title
        return card

    async def update_card(
        self,
        board_id: str,
        card_id: str,
        title: str | None = None,
        description: str | None = None,
    ) -> WekanCard:
        card = await self.find_card(board_id, card_id)
        if not card:
            raise ValueError(f"Card no encontrada: {card_id}")

        payload: dict = {}
        if title is not None:
            payload["title"] = title
        if description is not None:
            payload["description"] = description
        if not payload:
            return card

        await self._request(
            "PUT",
            f"/boards/{board_id}/lists/{card.list_id}/cards/{card_id}",
            json=payload,
        )
        if title is not None:
            card.title = title
        if description is not None:
            card.description = description
        return card


def format_boards(boards: list[WekanBoard]) -> str:
    if not boards:
        return "No hay tableros."
    return "\n".join(f"- {b.title} (id: {b.id})" for b in boards)


def format_cards(cards: list[WekanCard]) -> str:
    if not cards:
        return "No hay cards."
    lines = []
    for c in cards:
        desc = f" — {c.description[:80]}" if c.description else ""
        lines.append(f"- [{c.list_title}] {c.title} (id: {c.id}){desc}")
    return "\n".join(lines)
