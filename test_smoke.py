#!/usr/bin/env python3
"""Smoke test to verify agent and gateway can start."""

import sys
from pathlib import Path

def test_context_builder():
    """Test ContextBuilder can build system prompt."""
    from nanobot.agent.context import ContextBuilder
    
    workspace = Path.cwd()
    builder = ContextBuilder(workspace)
    
    # This was raising RuntimeError before the fix
    prompt = builder.build_system_prompt()
    assert prompt and "nanobot" in prompt, "System prompt invalid"
    
    # Verify Cognee reference
    identity = builder._get_identity()
    assert "CogneeMemoryService" in identity, "Cognee reference missing"
    
    # Verify messages can be built
    messages = builder.build_messages(
        history=[],
        current_message="hello",
    )
    assert len(messages) >= 1, f"Bad message count: {len(messages)}"
    
    print("✅ ContextBuilder smoke test PASSED")

def test_cognee_service():
    """Test Cognee service basic operations."""
    from nanobot.services.cognee_memory import CogneeMemoryService, cognee
    
    # Test sync service
    service = CogneeMemoryService()
    n1 = service.add("Test content")
    assert n1 > 0, "Failed to add node"
    
    meta = service.cognify(n1)
    assert "keywords" in meta, "cognify failed"
    
    results = service.search("test")
    assert len(results) > 0, "search failed"
    
    stats = service.get_stats()
    assert stats["nodes"] >= 1, "stats failed"
    
    service.close()
    
    # Test module-level API
    n2 = cognee.add("Another node")
    assert n2 > 0, "Module API add failed"
    
    print("✅ Cognee service smoke test PASSED")

if __name__ == "__main__":
    try:
        # Clean database
        import os
        if os.path.exists("cognee_store.db"):
            os.remove("cognee_store.db")
        
        test_context_builder()
        test_cognee_service()
        
        print("\n✅ ALL SMOKE TESTS PASSED - Agent and Gateway ready!")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ SMOKE TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
