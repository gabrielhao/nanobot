import asyncio
from typing import Any

import pytest


pytestmark = pytest.mark.asyncio


async def _run(coro: Any) -> Any:
    """Helper to run async methods inside plain tests if needed."""
    return await coro


def test_cognee_memory_service_basic_persistence(monkeypatch):
    """
    Phase A (Red): Basic Persistence

    Verifies that the CogneeMemoryService orchestrates add(), cognify(), and search()
    in the expected order when ingesting a session slice and performing a query.
    """
    from nanobot.services.cognee_memory import CogneeMemoryService

    calls: list[str] = []

    class DummyResult:
        def __init__(self, answer: str) -> None:
            self.answer = answer

    async def fake_add(*args, **kwargs):
        calls.append("add")

    async def fake_cognify(*args, **kwargs):
        calls.append("cognify")

    async def fake_memify(*args, **kwargs):
        calls.append("memify")

    async def fake_search(*args, **kwargs):
        calls.append("search")
        return [DummyResult("ok")]

    # Patch cognee top-level API
    from nanobot.services import cognee_memory as memory_module

    monkeypatch.setattr(memory_module.cognee, "add", fake_add)
    monkeypatch.setattr(memory_module.cognee, "cognify", fake_cognify)
    monkeypatch.setattr(memory_module.cognee, "memify", fake_memify)
    monkeypatch.setattr(memory_module.cognee, "search", fake_search)

    service = CogneeMemoryService(dataset_name="test_dataset")

    messages = [
        {"role": "user", "content": "Hello", "timestamp": "2026-01-01T00:00:00"},
        {"role": "assistant", "content": "Hi there!", "timestamp": "2026-01-01T00:00:01"},
    ]

    async def scenario():
        await service.ingest_session_messages("cli:1", messages)
        result = await service.search_graph_completion("Hi?", "cli:1")
        return result

    result = asyncio.run(scenario())

    assert isinstance(result, list)
    # At least one add, then cognify, then memify, then search somewhere after.
    assert "add" in calls
    assert "cognify" in calls
    assert "memify" in calls
    assert "search" in calls
    # Order: all add calls must happen before cognify, which must happen before memify.
    first_cognify = calls.index("cognify")
    first_memify = calls.index("memify")
    assert all(calls[i] == "add" for i in range(first_cognify))
    assert first_cognify < first_memify


def test_cognee_memory_service_relationship_retrieval(monkeypatch):
    """
    Phase A (Red): Relationship Retrieval

    Ensures that GRAPH_COMPLETION-style search returns connected entities/relations
    and that the service exposes them in a usable structure.
    """
    from nanobot.services.cognee_memory import CogneeMemoryService

    class DummyNode:
        def __init__(self, id: str, label: str) -> None:
            self.id = id
            self.label = label

    class DummyEdge:
        def __init__(self, src: str, dst: str, rel: str) -> None:
            self.src = src
            self.dst = dst
            self.rel = rel

    class DummyResult:
        def __init__(self) -> None:
            self.answer = "User likes coffee and lives in Seattle"
            self.nodes = [
                DummyNode("u1", "User"),
                DummyNode("c1", "Coffee"),
                DummyNode("l1", "Seattle"),
            ]
            self.edges = [
                DummyEdge("u1", "c1", "LIKES"),
                DummyEdge("u1", "l1", "LIVES_IN"),
            ]

    async def fake_search(*args, **kwargs):
        return [DummyResult()]

    from nanobot.services import cognee_memory as memory_module

    monkeypatch.setattr(memory_module.cognee, "search", fake_search)

    service = CogneeMemoryService(dataset_name="test_dataset")

    async def scenario():
        graph_view = await service.search_graph_completion("What does the user like?", "cli:1")
        return graph_view

    graph_view = asyncio.run(scenario())

    # Expect an answer plus structured links
    assert graph_view[0]["answer"].startswith("User likes coffee")
    assert {"src": "u1", "dst": "c1", "rel": "LIKES"} in graph_view[0]["edges"]
    assert {"src": "u1", "dst": "l1", "rel": "LIVES_IN"} in graph_view[0]["edges"]


def test_cognee_memory_service_edge_cases(monkeypatch):
    """
    Phase A (Red): Edge cases for empty strings, duplicates, and large text.
    """
    from nanobot.services.cognee_memory import CogneeMemoryService

    calls: list[Any] = []

    async def fake_add(*args, **kwargs):
        calls.append(kwargs.get("data") or args[0])

    async def fake_cognify(*args, **kwargs):
        return None

    async def fake_memify(*args, **kwargs):
        return None

    async def fake_search(*args, **kwargs):
        return []

    from nanobot.services import cognee_memory as memory_module

    monkeypatch.setattr(memory_module.cognee, "add", fake_add)
    monkeypatch.setattr(memory_module.cognee, "cognify", fake_cognify)
    monkeypatch.setattr(memory_module.cognee, "memify", fake_memify)
    monkeypatch.setattr(memory_module.cognee, "search", fake_search)

    service = CogneeMemoryService(dataset_name="test_dataset")

    big_text = "x" * 10_000
    messages = [
        {"role": "user", "content": "", "timestamp": "2026-01-01T00:00:00"},
        {"role": "user", "content": "duplicate", "timestamp": "2026-01-01T00:00:01"},
        {"role": "user", "content": "duplicate", "timestamp": "2026-01-01T00:00:02"},
        {"role": "user", "content": big_text, "timestamp": "2026-01-01T00:00:03"},
    ]

    async def scenario():
        await service.ingest_session_messages("cli:1", messages)

    asyncio.run(scenario())

    # Expect that empty content was filtered out, duplicates deduplicated, and big text accepted once.
    non_empty = [c for c in calls if c]
    assert sum("duplicate" in c for c in non_empty) == 1
    assert any(isinstance(c, str) and c.startswith("[UNTRUSTED SESSION MESSAGE]") for c in non_empty)
    assert any(isinstance(c, str) and c.endswith("... [truncated]") for c in non_empty)


def test_cognee_memory_service_validates_identity(monkeypatch):
    """
    Phase B (Green): Validate roles/user identities and sanitize content before ingest.
    """
    from nanobot.services.cognee_memory import CogneeMemoryService  # type: ignore[import-error]

    calls: list[dict[str, Any]] = []

    async def fake_add(*args, **kwargs):
        calls.append(kwargs)

    async def fake_cognify(*args, **kwargs):
        return None

    async def fake_memify(*args, **kwargs):
        return None

    from nanobot.services import cognee_memory as memory_module

    monkeypatch.setattr(memory_module.cognee, "add", fake_add)
    monkeypatch.setattr(memory_module.cognee, "cognify", fake_cognify)
    monkeypatch.setattr(memory_module.cognee, "memify", fake_memify)

    service = CogneeMemoryService(dataset_name="test_dataset")

    messages = [
        {"role": "user", "content": "Keep this", "timestamp": "2026-01-01T00:00:00", "user_id": "user-123"},
        {"role": "hacker", "content": "DROP TABLE", "timestamp": "2026-01-01T00:00:01", "user_id": "evil"},
    ]

    async def scenario():
        await service.ingest_session_messages(
            "cli:1",
            messages,
            expected_user_id="user-123",
            expected_session_key="cli:1",
        )

    asyncio.run(scenario())

    assert len(calls) == 1
    assert calls[0]["metadata"]["user_id"] == "user-123"
    assert calls[0]["metadata"]["session_key"] == "cli:1"
    assert calls[0]["metadata"]["role"] == "user"
    assert calls[0]["metadata"]["untrusted_source"] is True
    assert calls[0]["data"].startswith("[UNTRUSTED SESSION MESSAGE]")
    assert "DROP TABLE" not in calls[0]["data"]


def test_cognee_memory_service_error_handling(monkeypatch):
    """
    Phase A (Red): Error handling for upstream LLM / DB failures.
    """
    from nanobot.services.cognee_memory import CogneeMemoryService, CogneeMemoryError

    async def failing_add(*args, **kwargs):
        raise RuntimeError("LLM timeout")

    from nanobot.services import cognee_memory as memory_module

    monkeypatch.setattr(memory_module.cognee, "add", failing_add)

    service = CogneeMemoryService(dataset_name="test_dataset")

    messages = [
        {"role": "user", "content": "hello", "timestamp": "2026-01-01T00:00:00"},
    ]

    async def scenario():
        await service.ingest_session_messages("cli:1", messages)

    with pytest.raises(CogneeMemoryError) as excinfo:
        asyncio.run(scenario())

    assert "LLM timeout" in str(excinfo.value)


def test_cognee_memory_service_delete_user_nodes(monkeypatch):
    """
    Phase A (Red): Data privacy - delete_user_nodes(user_id) should call underlying
    Cognee delete / pruning logic with the correct filters and enforce caller identity.
    """
    from nanobot.services.cognee_memory import CogneeMemoryService

    called: dict[str, Any] = {}

    async def fake_delete_nodes(*args, **kwargs):
        called.append(kwargs)

    from nanobot.services import cognee_memory as memory_module

    monkeypatch.setattr(memory_module.cognee, "delete_nodes", fake_delete_nodes)

    service = CogneeMemoryService(dataset_name="test_dataset")

    async def scenario():
        await service.delete_user_nodes("user-123", authenticated_user_id="user-123")

    asyncio.run(scenario())

    assert called["kwargs"]["user_id"] == "user-123"
    assert called["kwargs"]["dataset"] == "test_dataset"
