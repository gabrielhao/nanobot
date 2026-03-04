#!/usr/bin/env python3
"""
Migration script to convert Nanobot's legacy file-based memory (MEMORY.md and HISTORY.md)
to the new Cognee-backed graph memory system.

Usage:
    python scripts/migrate_to_cognee.py /path/to/workspace
"""

import sys
import asyncio
import shutil
from pathlib import Path

# Add the root directory to sys.path so we can import nanobot
sys.path.insert(0, str(Path(__file__).parent.parent))

from nanobot.services.cognee_memory import CogneeMemoryService

async def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/migrate_to_cognee.py /path/to/workspace")
        sys.exit(1)

    workspace_dir = Path(sys.argv[1]).resolve()
    old_memory_dir = workspace_dir / "memory"
    backup_dir = workspace_dir / "memory_legacy_backup"
    
    if not old_memory_dir.exists():
        print(f"No legacy memory directory found at {old_memory_dir}.")
        print("Nothing to migrate.")
        return

    print(f"Starting Cognee Migration for workspace: {workspace_dir}")
    
    # Initialize the new Cognee service
    # We store the new database files inside the workspace just like before.
    # Depending on how the provider configures it, we can put it in `.cognee` or similar.
    # For now, we will use workspace_dir / ".cognee_db" as the root directory to keep it clean.
    cognee_db_dir = workspace_dir / ".cognee_db"
    cognee_service = CogneeMemoryService(workspace_dir=str(cognee_db_dir))
    
    memory_md = old_memory_dir / "MEMORY.md"
    history_md = old_memory_dir / "HISTORY.md"
    
    has_imported_data = False
    
    try:
        if memory_md.exists():
            print("Importing MEMORY.md (Long-term Facts)...")
            content = memory_md.read_text(encoding="utf-8")
            if content.strip():
                await cognee_service.add(content, session_key="legacy_base")
                print(" -> Added to memory graph queue.")
                has_imported_data = True
                
        if history_md.exists():
            print("Importing HISTORY.md (Episodic Events)...")
            content = history_md.read_text(encoding="utf-8")
            if content.strip():
                # We could split history by line, but sending the block is standard for Cognee's chunker
                await cognee_service.add(content, session_key="legacy_history")
                print(" -> Added to memory graph queue.")
                has_imported_data = True
                
        if has_imported_data:
            print("Executing ECL Pipeline (Cognify)... This may take a minute.")
            # We cognify the specific datasets we just created
            await cognee_service.cognify(session_key="legacy_base")
            await cognee_service.cognify(session_key="legacy_history")
            print(" -> Graph generated and embedded successfully.")
        else:
            print("No text found in legacy files. Skipping Cognify.")
            
        # Optional Memify call for extra relations
        await cognee_service.memify()
        
    except Exception as e:
        print(f"FATAL ERROR during migration: {e}")
        sys.exit(1)
    finally:
        # Graceful database teardown
        await cognee_service.close()

    # Decommission legacy files by renaming the folder
    print(f"Archiving legacy memory folder to: {backup_dir}")
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    shutil.move(str(old_memory_dir), str(backup_dir))

    print("\n✅ Migration Complete. Legacy files archived.")

if __name__ == "__main__":
    asyncio.run(main())
