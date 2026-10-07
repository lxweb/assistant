import pytest
from pathlib import Path

from assistant.tasks import TaskStatus, TaskStore


@pytest.mark.asyncio
async def test_recover_stuck_tasks(tmp_path: Path) -> None:
    db = tmp_path / "tasks.db"
    store = TaskStore(db)
    await store.init()

    task = await store.create(1, "tarea colgada")
    await store.update_status(task.id, TaskStatus.PROCESSING)

    recovered = await store.recover_stuck()
    assert recovered == 1

    updated = await store.get(task.id)
    assert updated.status == TaskStatus.PENDING
