#!/usr/bin/env python3
"""One-time migration of legacy file memory/session artifacts into Cognee.

Usage:
  python3 migrate_to_cognee.py --workspace ~/.nanobot/workspace

After a successful migration, legacy files are archived under:
  <workspace>/archive/legacy-memory-<timestamp>/
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nanobot.agent.memory import CogneeMemoryService


def _parse_session_jsonl(path: Path) -> tuple[str, list[dict[str, Any]]]:
    key = path.stem.replace("_", ":", 1)
    messages: list[dict[str, Any]] = []

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            if data.get("_type") == "metadata":
                key = data.get("key") or key
                continue
            if "role" in data:
                messages.append(data)

    return key, messages


def _archive_files(workspace: Path, files: list[Path]) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive_root = workspace / "archive" / f"legacy-memory-{stamp}"
    archive_root.mkdir(parents=True, exist_ok=True)

    for src in files:
        if not src.exists():
            continue
        rel = src.relative_to(workspace) if src.is_relative_to(workspace) else Path(src.name)
        dst = archive_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))

    return archive_root


async def migrate(workspace: Path, delete_after_archive: bool) -> None:
    service = CogneeMemoryService(workspace)
    migrated_files: list[Path] = []

    # Migrate long-term/history text artifacts as legacy records.
    for legacy in (workspace / "memory" / "MEMORY.md", workspace / "memory" / "HISTORY.md"):
        if legacy.exists():
            text = legacy.read_text(encoding="utf-8").strip()
            if text:
                await service.ingest_turn(
                    session_key="legacy:memory",
                    user_id="legacy-migration",
                    channel="system",
                    chat_id="migration",
                    messages=[
                        {
                            "role": "assistant",
                            "content": f"[{legacy.name}]\n{text}",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    ],
                )
            migrated_files.append(legacy)

    # Migrate session JSONL files.
    sessions_dir = workspace / "sessions"
    if sessions_dir.exists():
        for path in sorted(sessions_dir.glob("*.jsonl")):
            key, messages = _parse_session_jsonl(path)
            if messages:
                user_id = None
                if ":" in key:
                    # session key format is typically channel:chat_id
                    user_id = key.split(":", 1)[1]
                await service.ingest_turn(
                    session_key=key,
                    user_id=user_id,
                    channel="system",
                    chat_id="migration",
                    messages=messages,
                )
            migrated_files.append(path)

    if migrated_files:
        archive_root = _archive_files(workspace, migrated_files)
        print(f"Archived legacy files to: {archive_root}")

        if delete_after_archive:
            shutil.rmtree(archive_root)
            print("Deleted archived legacy files (--delete-after-archive enabled).")
    else:
        print("No legacy memory files found to migrate.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate legacy nanobot memory files to Cognee")
    parser.add_argument("--workspace", default="~/.nanobot/workspace", help="Workspace path")
    parser.add_argument(
        "--delete-after-archive",
        action="store_true",
        help="Delete archived legacy files after migration completes",
    )

    args = parser.parse_args()
    ws = Path(args.workspace).expanduser().resolve()
    asyncio.run(migrate(ws, args.delete_after_archive))
