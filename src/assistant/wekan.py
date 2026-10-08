import asyncio
import copy
import logging
import secrets
import string
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

# Nombre amigable para swimlanes de Wekan (filas horizontales del tablero).
SECTION_SINGULAR = "sección"
SECTION_PLURAL = "secciones"

WORKSPACE_WRITE_HELP = (
    "Wekan no expone la API REST para modificar espacios de trabajo. "
    "Configura WEKAN_MONGO_URL (ej. mongodb://ferretdb:27017/wekan) "
    "y conecta el contenedor assistant a la red docker de Wekan."
)


def _new_workspace_id() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(17))


def _workspaces_to_raw(workspaces: list["WekanWorkspace"]) -> list[dict]:
    return [
        {
            "id": ws.id,
            "name": ws.name,
            "children": _workspaces_to_raw(ws.children),
        }
        for ws in workspaces
    ]


def _collect_workspace_ids(node: dict, out: list[str]) -> None:
    out.append(node["id"])
    for child in node.get("children") or []:
        _collect_workspace_ids(child, out)


def _remove_workspace_from_raw(tree: list, workspace_id: str) -> tuple[list, list[str]]:
    removed: list[str] = []

    def walk(nodes: list) -> bool:
        for index, node in enumerate(nodes):
            if node["id"] == workspace_id:
                _collect_workspace_ids(node, removed)
                nodes.pop(index)
                return True
            children = node.get("children") or []
            if children and walk(children):
                return True
        return False

    cloned = copy.deepcopy(tree)
    if not walk(cloned):
        return cloned, []
    return cloned, removed


def _insert_workspace_raw(
    tree: list, parent_id: str | None, node: dict
) -> list:
    cloned = copy.deepcopy(tree)
    if not parent_id:
        cloned.append(node)
        return cloned

    def walk(nodes: list) -> bool:
        for item in nodes:
            if item["id"] == parent_id:
                item.setdefault("children", []).append(node)
                return True
            if walk(item.get("children") or []):
                return True
        return False

    if not walk(cloned):
        raise ValueError(f"Espacio de trabajo padre no encontrado: {parent_id}")
    return cloned


def _update_workspace_raw(
    tree: list, workspace_id: str, *, name: str | None = None
) -> list:
    cloned = copy.deepcopy(tree)

    def walk(nodes: list) -> bool:
        for item in nodes:
            if item["id"] == workspace_id:
                if name is not None:
                    item["name"] = name
                return True
            if walk(item.get("children") or []):
                return True
        return False

    if not walk(cloned):
        raise ValueError(f"Espacio de trabajo no encontrado: {workspace_id}")
    return cloned


@dataclass
class WekanWorkspace:
    id: str
    name: str
    children: list["WekanWorkspace"] = field(default_factory=list)


@dataclass
class WekanBoard:
    id: str
    title: str
    slug: str | None = None
    workspace_id: str | None = None


@dataclass
class WekanList:
    id: str
    title: str


@dataclass
class WekanSwimlane:
    id: str
    title: str


@dataclass
class WekanCard:
    id: str
    title: str
    description: str
    list_id: str
    list_title: str
    swimlane_id: str | None = None
    swimlane_title: str | None = None


class WekanClient:
    def __init__(
        self,
        api_url: str,
        token: str,
        author_id: str,
        user_id: str,
        public_url: str = "http://wekan.home.lan",
        mongo_url: str | None = None,
    ) -> None:
        self._api_url = api_url.rstrip("/")
        self._token = token
        self._author_id = author_id
        self._user_id = user_id
        self._public_url = public_url.rstrip("/")
        self._mongo_url = mongo_url.rstrip("/") if mongo_url else None

    @property
    def available(self) -> bool:
        return bool(self._api_url and self._token and self._author_id)

    @property
    def workspace_writes_enabled(self) -> bool:
        return bool(self._mongo_url)

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

    async def get_user(self) -> dict:
        return await self._request("GET", "/user")

    @staticmethod
    def _parse_workspace_tree(nodes: list | None) -> list[WekanWorkspace]:
        if not nodes:
            return []
        workspaces: list[WekanWorkspace] = []
        for node in nodes:
            workspaces.append(
                WekanWorkspace(
                    id=node["id"],
                    name=node["name"],
                    children=WekanClient._parse_workspace_tree(node.get("children")),
                )
            )
        return workspaces

    @staticmethod
    def _flatten_workspaces(
        workspaces: list[WekanWorkspace],
    ) -> dict[str, WekanWorkspace]:
        by_id: dict[str, WekanWorkspace] = {}
        for ws in workspaces:
            by_id[ws.id] = ws
            by_id.update(WekanClient._flatten_workspaces(ws.children))
        return by_id

    async def _workspace_context(self) -> tuple[list[WekanWorkspace], dict[str, str]]:
        user = await self.get_user()
        profile = user.get("profile", {})
        tree = self._parse_workspace_tree(profile.get("boardWorkspacesTree"))
        assignments = profile.get("boardWorkspaceAssignments") or {}
        return tree, assignments

    async def list_workspaces(self) -> list[WekanWorkspace]:
        tree, _ = await self._workspace_context()
        return tree

    async def find_workspace(self, name: str) -> WekanWorkspace | None:
        name_lower = name.lower().strip()
        tree, _ = await self._workspace_context()
        for ws in self._flatten_workspaces(tree).values():
            if ws.id == name or ws.name.lower() == name_lower:
                return ws
        for ws in self._flatten_workspaces(tree).values():
            if name_lower in ws.name.lower():
                return ws
        return None

    async def _load_workspace_raw(self) -> tuple[list, dict[str, str]]:
        user = await self.get_user()
        profile = user.get("profile", {})
        tree = copy.deepcopy(profile.get("boardWorkspacesTree") or [])
        assignments = copy.deepcopy(profile.get("boardWorkspaceAssignments") or {})
        return tree, assignments

    def _mongo_save_workspace_profile_sync(
        self, tree: list, assignments: dict[str, str]
    ) -> None:
        from pymongo import MongoClient

        client = MongoClient(self._mongo_url, serverSelectionTimeoutMS=8000)
        db = client.get_default_database()
        if db is None:
            db = client["wekan"]
        result = db["users"].update_one(
            {"_id": self._user_id},
            {
                "$set": {
                    "profile.boardWorkspacesTree": tree,
                    "profile.boardWorkspaceAssignments": assignments,
                }
            },
        )
        if result.matched_count == 0:
            raise ValueError("Usuario Wekan no encontrado en la base de datos")

    async def _save_workspace_raw(
        self, tree: list, assignments: dict[str, str]
    ) -> None:
        if not self._mongo_url:
            raise ValueError(WORKSPACE_WRITE_HELP)
        await asyncio.to_thread(
            self._mongo_save_workspace_profile_sync, tree, assignments
        )

    async def create_workspace(
        self, name: str, parent: str | None = None
    ) -> WekanWorkspace:
        name = name.strip()
        if not name:
            raise ValueError("El nombre del espacio de trabajo es obligatorio")

        tree, assignments = await self._load_workspace_raw()
        parent_id = None
        if parent:
            found = await self.find_workspace(parent)
            if not found:
                raise ValueError(f"Espacio de trabajo padre no encontrado: {parent}")
            parent_id = found.id

        node = {"id": _new_workspace_id(), "name": name, "children": []}
        tree = _insert_workspace_raw(tree, parent_id, node)
        await self._save_workspace_raw(tree, assignments)
        return WekanWorkspace(id=node["id"], name=name)

    async def update_workspace(
        self,
        workspace: str,
        new_name: str | None = None,
    ) -> WekanWorkspace:
        found = await self.find_workspace(workspace)
        if not found:
            raise ValueError(f"Espacio de trabajo no encontrado: {workspace}")
        if new_name is not None:
            new_name = new_name.strip()
            if not new_name:
                raise ValueError("El nuevo nombre no puede estar vacío")

        tree, assignments = await self._load_workspace_raw()
        tree = _update_workspace_raw(tree, found.id, name=new_name)
        await self._save_workspace_raw(tree, assignments)
        return WekanWorkspace(
            id=found.id,
            name=new_name if new_name is not None else found.name,
        )

    async def delete_workspace(self, workspace: str) -> str:
        found = await self.find_workspace(workspace)
        if not found:
            raise ValueError(f"Espacio de trabajo no encontrado: {workspace}")

        tree, assignments = await self._load_workspace_raw()
        tree, removed_ids = _remove_workspace_from_raw(tree, found.id)
        if not removed_ids:
            raise ValueError(f"Espacio de trabajo no encontrado: {workspace}")

        for board_id, space_id in list(assignments.items()):
            if space_id in removed_ids:
                del assignments[board_id]

        await self._save_workspace_raw(tree, assignments)
        return found.name

    async def assign_board_to_workspace(
        self, board_name: str, workspace_name: str
    ) -> str:
        board = await self.find_board(board_name)
        if not board:
            raise ValueError(f"Tablero no encontrado: {board_name}")
        ws = await self.find_workspace(workspace_name)
        if not ws:
            raise ValueError(f"Espacio de trabajo no encontrado: {workspace_name}")

        tree, assignments = await self._load_workspace_raw()
        assignments[board.id] = ws.id
        await self._save_workspace_raw(tree, assignments)
        return f"Tablero '{board.title}' asignado a '{ws.name}'."

    async def unassign_board_from_workspace(self, board_name: str) -> str:
        board = await self.find_board(board_name)
        if not board:
            raise ValueError(f"Tablero no encontrado: {board_name}")

        tree, assignments = await self._load_workspace_raw()
        if board.id not in assignments:
            return f"El tablero '{board.title}' no estaba en ningún espacio."
        del assignments[board.id]
        await self._save_workspace_raw(tree, assignments)
        return f"Tablero '{board.title}' movido a sin asignar."

    async def list_boards(self, workspace: str | None = None) -> list[WekanBoard]:
        data = await self._request("GET", f"/users/{self._user_id}/boards")
        boards = [WekanBoard(id=b["_id"], title=b["title"]) for b in data]
        _, assignments = await self._workspace_context()

        for board in boards:
            board.workspace_id = assignments.get(board.id)

        if not workspace:
            return boards

        ws = await self.find_workspace(workspace)
        if not ws:
            return []

        return [b for b in boards if b.workspace_id == ws.id]

    async def describe_workspace(self, name: str) -> str:
        ws = await self.find_workspace(name)
        if not ws:
            raise ValueError(f"Espacio de trabajo no encontrado: {name}")

        boards = await self.list_boards(ws.name)
        lines = [
            f"📂 *{ws.name}*",
            f"id: `{ws.id}`",
        ]
        if ws.children:
            child_names = ", ".join(c.name for c in ws.children)
            lines.append(f"Subespacios: {child_names}")

        lines.append("")
        lines.append(f"*Tableros* ({len(boards)}):")
        if not boards:
            lines.append("_(ninguno)_")
        else:
            for board in boards:
                detail = await self._request("GET", f"/boards/{board.id}")
                slug = detail.get("slug", board.id)
                url = f"{self._public_url}/b/{board.id}/{slug}"
                lines.append(f"• *{board.title}*")
                lines.append(f"  {url}")

        return "\n".join(lines)

    async def describe_board(self, name: str) -> str:
        board = await self.find_board(name)
        if not board:
            raise ValueError(f"Tablero no encontrado: {name}")

        detail = await self._request("GET", f"/boards/{board.id}")
        slug = detail.get("slug", board.id)
        url = f"{self._public_url}/b/{board.id}/{slug}"
        lists = await self.list_lists(board.id)
        swimlanes = await self.list_swimlanes(board.id)

        lines = [
            f"📋 *{board.title}*",
            f"id: `{board.id}`",
            url,
            "",
        ]

        if lists:
            lines.append("*Listas* (columnas):")
            for lst in lists:
                cards = await self._request(
                    "GET", f"/boards/{board.id}/lists/{lst.id}/cards"
                )
                lines.append(f"• {lst.title} — {len(cards)} tarea(s)")
            lines.append("")

        if swimlanes:
            label = SECTION_PLURAL.capitalize()
            lines.append(f"*{label}* (filas):")
            for sl in swimlanes:
                cards = await self._request(
                    "GET", f"/boards/{board.id}/swimlanes/{sl.id}/cards"
                )
                lines.append(f"• {sl.title} — {len(cards)} tarea(s)")
            lines.append("")

        total = len(await self.list_cards(board.id))
        lines.append(f"*Total tareas:* {total}")
        lines.append(
            f"Listar: /tareas {board.title}\n"
            f"Crear: /tareas crear <lista> <título>"
        )
        return "\n".join(lines).strip()

    async def list_boards_markdown(
        self, workspace: str | None = None
    ) -> str:
        boards = await self.list_boards(workspace)
        if not boards:
            if workspace:
                return f"No hay tableros en el espacio '{workspace}'."
            return "No hay tableros."

        header = (
            f"*Tableros* en espacio '{workspace}':\n\n"
            if workspace
            else "*Tableros:*\n\n"
        )
        parts: list[str] = [header]
        for board in boards:
            detail = await self._request("GET", f"/boards/{board.id}")
            slug = detail.get("slug", board.id)
            url = f"{self._public_url}/b/{board.id}/{slug}"
            n = len(await self.list_cards(board.id))
            parts.append(f"• *{board.title}* ({n} tareas)\n  {url}\n")
        return "".join(parts).strip()

    async def _append_board_overview(self, lines: list[str], board: WekanBoard) -> None:
        detail = await self._request("GET", f"/boards/{board.id}")
        slug = detail.get("slug", board.id)
        lists = await self.list_lists(board.id)
        swimlanes = await self.list_swimlanes(board.id)

        list_parts: list[str] = []
        for lst in lists:
            cards = await self._request(
                "GET", f"/boards/{board.id}/lists/{lst.id}/cards"
            )
            list_parts.append(f"{lst.title} ({len(cards)})")

        swimlane_parts: list[str] = []
        for sl in swimlanes:
            cards = await self._request(
                "GET", f"/boards/{board.id}/swimlanes/{sl.id}/cards"
            )
            swimlane_parts.append(f"{sl.title} ({len(cards)})")

        url = f"{self._public_url}/b/{board.id}/{slug}"
        lines.append(f"  • *{board.title}*")
        if list_parts:
            lines.append(f"    Listas: {', '.join(list_parts)}")
        if swimlane_parts:
            label = SECTION_PLURAL.capitalize()
            lines.append(f"    {label}: {', '.join(swimlane_parts)}")
        lines.append(f"    {url}")

    async def workspace_overview(self) -> str:
        user = await self.get_user()
        username = user.get("username", "unknown")
        tree, _ = await self._workspace_context()
        boards = await self.list_boards()
        by_workspace: dict[str, list[WekanBoard]] = {}
        unassigned: list[WekanBoard] = []

        for board in boards:
            if board.workspace_id:
                by_workspace.setdefault(board.workspace_id, []).append(board)
            else:
                unassigned.append(board)

        lines = [f"📋 *Usuario Wekan:* {username}\n"]

        for ws in tree:
            lines.append(f"*{ws.name}* (workspace):")
            ws_boards = by_workspace.get(ws.id, [])
            if not ws_boards:
                lines.append("  (sin tableros)")
            else:
                for board in ws_boards:
                    await self._append_board_overview(lines, board)
            lines.append("")

        if unassigned:
            lines.append("*Sin asignar* (boards fuera de workspaces):")
            for board in unassigned:
                await self._append_board_overview(lines, board)
            lines.append("")

        return "\n".join(lines).strip()

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

    async def list_swimlanes(self, board_id: str) -> list[WekanSwimlane]:
        data = await self._request("GET", f"/boards/{board_id}/swimlanes")
        return [WekanSwimlane(id=item["_id"], title=item["title"]) for item in data]

    async def find_list(self, board_id: str, name: str) -> WekanList | None:
        name_lower = name.lower().strip()
        for item in await self.list_lists(board_id):
            if item.id == name or item.title.lower() == name_lower:
                return item
        for item in await self.list_lists(board_id):
            if name_lower in item.title.lower():
                return item
        return None

    async def find_swimlane(self, board_id: str, name: str) -> WekanSwimlane | None:
        name_lower = name.lower().strip()
        for item in await self.list_swimlanes(board_id):
            if item.id == name or item.title.lower() == name_lower:
                return item
        for item in await self.list_swimlanes(board_id):
            if name_lower in item.title.lower():
                return item
        return None

    async def list_cards(
        self,
        board_id: str,
        list_name: str | None = None,
        swimlane_name: str | None = None,
    ) -> list[WekanCard]:
        lists = await self.list_lists(board_id)
        swimlanes = await self.list_swimlanes(board_id)

        if list_name:
            found = await self.find_list(board_id, list_name)
            lists = [found] if found else []
            if not lists:
                found_sl = await self.find_swimlane(board_id, list_name)
                swimlanes = [found_sl] if found_sl else []

        if swimlane_name:
            found = await self.find_swimlane(board_id, swimlane_name)
            swimlanes = [found] if found else []

        cards: list[WekanCard] = []
        seen: set[str] = set()

        for lst in lists:
            data = await self._request(
                "GET", f"/boards/{board_id}/lists/{lst.id}/cards"
            )
            for c in data:
                card_id = c["_id"]
                if card_id in seen:
                    continue
                seen.add(card_id)
                cards.append(
                    WekanCard(
                        id=card_id,
                        title=c.get("title", ""),
                        description=c.get("description", "") or "",
                        list_id=lst.id,
                        list_title=lst.title,
                        swimlane_id=c.get("swimlaneId"),
                    )
                )

        if not lists and swimlanes:
            for sl in swimlanes:
                data = await self._request(
                    "GET", f"/boards/{board_id}/swimlanes/{sl.id}/cards"
                )
                for c in data:
                    card_id = c["_id"]
                    if card_id in seen:
                        continue
                    seen.add(card_id)
                    cards.append(
                        WekanCard(
                            id=card_id,
                            title=c.get("title", ""),
                            description=c.get("description", "") or "",
                            list_id=c.get("listId", ""),
                            list_title="",
                            swimlane_id=sl.id,
                            swimlane_title=sl.title,
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
        raise ValueError(f"No se encontró {SECTION_SINGULAR} en el tablero")

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


def format_workspaces(workspaces: list[WekanWorkspace]) -> str:
    if not workspaces:
        return "No hay espacios de trabajo configurados."

    def walk(items: list[WekanWorkspace], indent: int = 0) -> list[str]:
        lines: list[str] = []
        prefix = "  " * indent
        for ws in items:
            lines.append(f"{prefix}- {ws.name} (id: {ws.id})")
            lines.extend(walk(ws.children, indent + 1))
        return lines

    return "Espacios de trabajo:\n" + "\n".join(walk(workspaces))


def format_boards(
    boards: list[WekanBoard],
    workspace_name: str | None = None,
) -> str:
    if not boards:
        if workspace_name:
            return f"No hay tableros en el workspace '{workspace_name}'."
        return "No hay tableros."
    header = (
        f"Tableros en workspace '{workspace_name}':\n"
        if workspace_name
        else "Tableros:\n"
    )
    body = "\n".join(f"- {b.title} (id: {b.id})" for b in boards)
    return header + body


def format_sections(swimlanes: list[WekanSwimlane]) -> str:
    if not swimlanes:
        return f"No hay {SECTION_PLURAL}."
    lines = [f"{SECTION_PLURAL.capitalize()}:"]
    for sl in swimlanes:
        lines.append(f"- {sl.title} (id: {sl.id})")
    return "\n".join(lines)


def format_cards(cards: list[WekanCard]) -> str:
    if not cards:
        return "No hay tareas."
    lines = []
    sec = SECTION_SINGULAR
    for c in cards:
        if c.list_title and c.swimlane_title:
            location = f"{c.list_title} / {sec} {c.swimlane_title}"
        elif c.list_title:
            location = c.list_title
        elif c.swimlane_title:
            location = f"{sec} {c.swimlane_title}"
        else:
            location = "?"
        desc = f" — {c.description[:80]}" if c.description else ""
        lines.append(f"- [{location}] {c.title} (id: {c.id}){desc}")
    return "\n".join(lines)
