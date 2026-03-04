"""Migration script to import legacy session and memory files into Cognee.

This script reads workspace `sessions/*.jsonl` and `memory/MEMORY.md` (if present)
and imports content into the Cognee graph using `cognee.add()` and `cognee.cognify()`.

Note: The legacy session manager has been removed from runtime; this script runs
independently and may be used to bootstrap the Cognee graph.
"""

from pathlib import Path
import json
import sys

from nanobot.services.cognee_memory import cognee


def migrate(workspace: str | None = None) -> None:
    ws = Path(workspace or Path.cwd())
    sessions_dir = ws / "sessions"
    memory_dir = ws / "memory"

    # Import MEMORY.md if exists
    mem_file = memory_dir / "MEMORY.md"
    if mem_file.exists():
        content = mem_file.read_text(encoding="utf-8")
        nid = cognee.add(content, metadata={"source": "MEMORY.md"})
        try:
            cognee.cognify(nid)
            print(f"Imported MEMORY.md -> node {nid}")
        except Exception as e:
            print(f"Cognify failed for MEMORY.md: {e}")

    # Import sessions JSONL files
    if sessions_dir.exists():
        for path in sessions_dir.glob("*.jsonl"):
            try:
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                        except Exception:
                            continue
                        if data.get("_type") == "metadata":
                            continue
                        content = data.get("content")
                        if not content:
                            continue
                        nid = cognee.add(content, metadata={"source": str(path.name), "role": data.get("role")})
                        try:
                            cognee.cognify(nid)
                        except Exception:
                            pass
                print(f"Imported session {path.name}")
            except Exception as e:
                print(f"Failed to import {path}: {e}")


if __name__ == "__main__":
    migrate(sys.argv[1] if len(sys.argv) > 1 else None)
