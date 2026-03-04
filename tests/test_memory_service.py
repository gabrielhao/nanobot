import pytest
import asyncio
import sqlite3
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from nanobot.services.cognee_memory import CogneeMemoryServiceAsync, SearchType

@pytest.fixture
def workspace(tmp_path):
    return tmp_path

@pytest.mark.asyncio
async def test_basic_persistence(workspace):
    """Test Phase A: Basic add, cognify, and search."""
    service = CogneeMemoryServiceAsync(workspace=workspace, db_name="test_cognee.db")
    
    content = "User prefers Python for data science."
    metadata = {"category": "preference"}
    
    node_id = await service.add(content, metadata)
    assert isinstance(node_id, int)
    
    # Test cognify (extraction/indexing simulation)
    updated_meta = await service.cognify(node_id)
    assert "keywords" in updated_meta
    assert "python" in [k.lower() for k in updated_meta["keywords"]]
    
    # Test search
    results = await service.search("Python preference")
    assert len(results) > 0
    assert any(content in r.content for r in results)
    
    await service.close()

@pytest.mark.asyncio
async def test_relationship_retrieval(workspace):
    """Test Phase A: Relationship/Graph retrieval."""
    service = CogneeMemoryServiceAsync(workspace=workspace, db_name="test_cognee_rel.db")
    
    id1 = await service.add("Python")
    id2 = await service.add("Data Science")
    
    # Link nodes
    await service.link(id1, id2, label="used_for")
    
    # Search with graph completion
    results = await service.search("Python", search_type=SearchType.GRAPH_COMPLETION)
    
    # Should find Python AND its neighbor Data Science
    contents = [r.content for r in results]
    assert "Python" in contents
    assert "Data Science" in contents
    
    await service.close()

@pytest.mark.asyncio
async def test_edge_cases(workspace):
    """Test Phase A: Empty strings, duplicates, massive blocks."""
    service = CogneeMemoryServiceAsync(workspace=workspace, db_name="test_cognee_edge.db")
    
    # Empty string (should handle gracefully, maybe return 0 or empty list)
    with pytest.raises(Exception): # Assuming content is NOT NULL
        await service.add("")
        
    # Massive block
    massive_text = "word " * 10000
    mid = await service.add(massive_text)
    assert mid > 0
    
    # Duplicate add
    id_a = await service.add("Duplicate content")
    id_b = await service.add("Duplicate content")
    assert id_a != id_b # Should create two nodes or handle deduplication logic
    
    await service.close()

@pytest.mark.asyncio
async def test_data_privacy_forget(workspace):
    """Test Phase A: Privacy 'forget' protocol."""
    service = CogneeMemoryServiceAsync(workspace=workspace, db_name="test_cognee_privacy.db")
    
    content = "Sensitive user data about Alice."
    await service.add(content)
    
    # Verify it exists
    results = await service.search("Alice")
    assert len(results) == 1
    
    # Forget
    deleted_count = await service.forget("Alice")
    assert deleted_count == 1
    
    # Verify it is gone
    results = await service.search("Alice")
    assert len(results) == 0
    
    await service.close()

@pytest.mark.asyncio
async def test_delete_user_nodes(workspace):
    """Test Phase A: Privacy 'delete_user_nodes' method."""
    service = CogneeMemoryServiceAsync(workspace=workspace, db_name="test_cognee_user_del.db")
    
    user_id = "user_123"
    await service.add("User 123 fact 1", metadata={"user_id": user_id})
    await service.add("User 123 fact 2", metadata={"user_id": user_id})
    await service.add("Other user fact", metadata={"user_id": "other"})
    
    # Delete user 123
    deleted_count = await service.delete_user_nodes(user_id)
    assert deleted_count == 2
    
    # Verify remaining
    results = await service.search("Other")
    assert len(results) >= 1
    
    # Verify deleted are gone
    results = await service.search("123")
    assert len(results) == 0
    
    await service.close()
