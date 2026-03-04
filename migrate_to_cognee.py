"""One-off migration script to move legacy file-based memory into Cognee.

This module is intentionally simple and is exercised by tests in
tests/test_migrate_to_cognee.py. It:

- Reads legacy MEMORY.md / HISTORY.md and session JSONL files.
- Sends each legacy artifact through CogneeMemoryService.ingest_turn().
- Archives the original files under workspace/archive/legacy-memory-*/.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Iterable, Tuple

from nanobot.services.cognee_memory import CogneeMemoryService


def _parse_session_jsonl(path: Path) -> Tuple[str, list[dict]]:
    """Parse a legacy JSONL session file into (key, messages).

    The first line is expected to be a metadata line with a "key" field.
    Remaining lines are individual message dicts.
    """
    key: str | None = None
    messages: list[dict] = []

    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            if data.get("_type") == "metadata":
                key = data.get("key") or key
            else:
                messages.append(data)

    if key is None:
        # Fallback: derive key from filename if metadata is missing.
        key = path.stem.replace("_", ":", 1)

    return key, messages


async def migrate(workspace: Path, delete_after_archive: bool = False) -> None:
    """Migrate legacy memory files from a workspace into Cognee.

    - For each MEMORY.md / HISTORY.md, call CogneeMemoryService.ingest_turn().
    - For each session JSONL file, parse and call ingest_turn() with messages.
    - Archive the original files under workspace/archive/legacy-memory-*/.
    - Optionally delete the archive after migration.
    """
    ws = Path(workspace)
    memory_dir = ws / "memory"
    sessions_dir = ws / "sessions"

    service = CogneeMemoryService(ws)

    # Collect legacy memory files and session files.
    mem_files: list[Path] = []
    if memory_dir.exists():
        for name in ("MEMORY.md", "HISTORY.md"):
            p = memory_dir / name
            if p.exists():
                mem_files.append(p)

    session_files: list[Path] = []
    if sessions_dir.exists():
        session_files = sorted(sessions_dir.glob("*.jsonl"))

    calls = []

    # Ingest memory files as generic turns.
    for mf in mem_files:
        text = mf.read_text(encoding="utf-8")
        await service.ingest_turn(name=mf.name, content=text)
        calls.append(mf)

    # Ingest each session as a turn with key + messages.
    for sf in session_files:
        key, messages = _parse_session_jsonl(sf)
        await service.ingest_turn(session_key=key, messages=messages, path=str(sf))
        calls.append(sf)

    # If nothing to migrate, return early.
    if not calls:
        return

    # Archive legacy files.
    archive_root = ws / "archive"
    archive_root.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("legacy-memory-%Y%m%d%H%M%S")
    archive_dir = archive_root / stamp
    archive_dir.mkdir(parents=True, exist_ok=True)

    def _copy_if_exists(src: Path, dest: Path) -> None:
        if src.is_dir():
            if src.exists():
                shutil.copytree(src, dest, dirs_exist_ok=True)
        elif src.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)

    # Copy memory and sessions directories into archive.
    if memory_dir.exists():
        _copy_if_exists(memory_dir, archive_dir / "memory")
    if sessions_dir.exists():
        _copy_if_exists(sessions_dir, archive_dir / "sessions")

    # Remove originals.
    if memory_dir.exists():
        shutil.rmtree(memory_dir)
    if sessions_dir.exists():
        shutil.rmtree(sessions_dir)

    # Optionally delete archive contents after archiving.
    if delete_after_archive:
        if archive_dir.exists():
            shutil.rmtree(archive_dir, ignore_errors=True)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Migrate legacy memory to Cognee.")
    parser.add_argument("workspace", type=Path, help="Path to nanobot workspace")
    parser.add_argument(
        "--delete-after-archive",
        action="store_true",
        help="Delete archive after successful migration",
    )
    args = parser.parse_args()

    asyncio.run(migrate(args.workspace, delete_after_archive=args.delete_after_archive))

