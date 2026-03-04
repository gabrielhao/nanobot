import pytest
import asyncio
from datetime import datetime, timedelta
from nanobot.services.cognee_memory import CogneeMemoryServiceAsync, SearchType

@pytest.fixture
def workspace(tmp_path):
    return tmp_path

@pytest.mark.asyncio
async def test_temporal_decay(workspace):
    """Test that recent memories are prioritized."""
    service = CogneeMemoryServiceAsync(workspace=workspace, db_name="test_decay.db")
    
    # Add an old fact
    old_fact_id = await service.add("User likes Java")
    conn = service._sync_service._conn
    cur = conn.cursor()
    thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
    cur.execute("UPDATE nodes SET updated_at = ? WHERE id = ?", (thirty_days_ago, old_fact_id))
    conn.commit()

    # Add a new fact
    new_fact_id = await service.add("User likes Python")
    await service.cognify(new_fact_id)
    
    # Search for a generic term present in both
    results = await service.search("User likes")
    
    assert len(results) > 0
    assert results[0].content == "User likes Python", "Newer fact should be ranked higher"
    
    await service.close()

@pytest.mark.asyncio
async def test_context_budgeting(workspace):
    """Test that search respects the max_chars budget."""
    service = CogneeMemoryServiceAsync(workspace=workspace, db_name="test_budget.db")
    
    await service.add("short fact")
    await service.add("This is a much longer fact that should not be included")
    
    results = await service.search("fact", max_chars=20)
    
    assert len(results) == 1
    assert results[0].content == "short fact"
    
    await service.close()

@pytest.mark.asyncio
async def test_empty_query(workspace):
    """Test that an empty query returns no results."""
    service = CogneeMemoryServiceAsync(workspace=workspace, db_name="test_empty_q.db")
    await service.add("some content")
    
    results = await service.search("")
    assert len(results) == 0
    
    results_ws = await service.search("   ")
    assert len(results_ws) == 0
    
    await service.close()
