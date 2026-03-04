"""Caching layer for system prompts to reduce token costs."""

import hashlib
from pathlib import Path
from typing import Any


class PromptCache:
    """Cache system prompts by content hash. Invalidates when source files change."""

    def __init__(self):
        self._cache: dict[str, str] = {}  # hash -> prompt content
        self._file_hashes: dict[str, str] = {}  # filepath -> hash

    def get_or_build(
        self,
        workspace: Path,
        builder_func: callable,
        *args,
        **kwargs,
    ) -> tuple[str, bool]:
        """
        Get cached system prompt or build new one.

        Args:
            workspace: Path to workspace (for detecting file changes)
            builder_func: Function that builds the system prompt
            args/kwargs: Arguments to pass to builder_func

        Returns:
            (prompt_content, was_cached)
        """
        # Compute hash of all source files
        files_to_check = [
            workspace / "AGENTS.md",
            workspace / "SOUL.md",
            workspace / "USER.md",
            workspace / "TOOLS.md",
            workspace / "IDENTITY.md",
            workspace / "memory" / "MEMORY.md",
        ]

        current_hash = self._compute_files_hash(files_to_check)

        # Check if we have a cached version
        if current_hash in self._cache:
            return self._cache[current_hash], True

        # Build new prompt
        prompt = builder_func(*args, **kwargs)
        self._cache[current_hash] = prompt

        # Keep cache size bounded (LRU-like: max 5 prompts)
        if len(self._cache) > 5:
            # Remove oldest entry (simple FIFO)
            self._cache.pop(next(iter(self._cache)))

        return prompt, False

    @staticmethod
    def _compute_files_hash(filepaths: list[Path]) -> str:
        """Compute combined hash of files (based on existence and mod time)."""
        hasher = hashlib.md5()
        for fpath in filepaths:
            if fpath.exists():
                # Hash filename + mod time (not content, for speed)
                stat_str = f"{fpath}:{fpath.stat().st_mtime_ns}"
                hasher.update(stat_str.encode())
            else:
                hasher.update(b"missing")
        return hasher.hexdigest()
