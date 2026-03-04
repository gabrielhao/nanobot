"""Memory archival and lifecycle management for long-term facts."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger


class MemoryArchive:
    """
    Manage memory lifecycle: active vs. archived facts.

    Active (MEMORY.md): ~50 recent, high-relevance facts
    Archive (MEMORY.archive.json): All historical facts with metadata
    """

    def __init__(self, workspace: Path):
        self.memory_dir = workspace / "memory"
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.archive_file = self.memory_dir / "MEMORY.archive.json"

    def load_archive(self) -> dict[str, Any]:
        """Load archived facts with metadata."""
        if not self.archive_file.exists():
            return {}
        try:
            return json.loads(self.archive_file.read_text(encoding="utf-8")) or {}
        except Exception:
            logger.warning("Failed to load memory archive")
            return {}

    def save_archive(self, archive: dict[str, Any]) -> None:
        """Save archive to disk."""
        self.archive_file.write_text(json.dumps(archive, ensure_ascii=False, indent=2), encoding="utf-8")

    def parse_facts_from_memory(self, memory_text: str) -> list[dict[str, str]]:
        """
        Parse markdown facts from MEMORY.md.

        Format:
        ## Section
        - Fact 1
        - Fact 2
        """
        facts = []
        current_section = None

        for line in memory_text.split("\n"):
            line = line.rstrip()
            if line.startswith("## "):
                current_section = line.replace("## ", "").strip()
            elif line.startswith("- ") and current_section:
                fact_text = line.replace("- ", "").strip()
                facts.append({"section": current_section, "text": fact_text})

        return facts

    def prune_memory(
        self,
        current_memory: str,
        archive: dict[str, Any],
        max_active_facts: int = 50,
    ) -> tuple[str, dict[str, Any]]:
        """
        Prune MEMORY.md to keep only top N active facts.

        Older/less-used facts moved to archive.

        Returns:
            (pruned_memory_md, updated_archive)
        """
        facts = self.parse_facts_from_memory(current_memory)
        if len(facts) <= max_active_facts:
            return current_memory, archive

        # Score facts by recency (last updated) and frequency (merge count)
        scored = []
        for i, fact in enumerate(facts):
            fact_id = f"{fact['section']}:{fact['text']}"
            archived_entry = archive.get(fact_id, {})

            # Score: higher = keep active
            recency_score = 100 - i  # Earlier in list = more recent
            frequency = archived_entry.get("frequency", 0)
            merged_count = archived_entry.get("merged", 1)

            score = recency_score + (frequency * 10) + (merged_count * 5)
            scored.append((score, fact))

        # Sort by score descending, keep top N
        scored.sort(key=lambda x: x[0], reverse=True)
        active_facts = [f for _, f in scored[:max_active_facts]]
        to_archive = [f for _, f in scored[max_active_facts:]]

        # Update archive with pruned facts
        for fact in to_archive:
            fact_id = f"{fact['section']}:{fact['text']}"
            if fact_id in archive:
                archive[fact_id]["archived_at"] = datetime.now().isoformat()
                archive[fact_id]["active"] = False
            else:
                archive[fact_id] = {
                    "text": fact["text"],
                    "section": fact["section"],
                    "created_at": datetime.now().isoformat(),
                    "archived_at": datetime.now().isoformat(),
                    "frequency": 0,
                    "merged": 1,
                    "active": False,
                }

        # Track active facts
        for fact in active_facts:
            fact_id = f"{fact['section']}:{fact['text']}"
            if fact_id in archive:
                archive[fact_id]["active"] = True
                archive[fact_id]["last_seen"] = datetime.now().isoformat()

        # Rebuild MEMORY.md from active facts
        by_section = {}
        for fact in active_facts:
            section = fact["section"]
            if section not in by_section:
                by_section[section] = []
            by_section[section].append(fact["text"])

        lines = []
        for section in sorted(by_section.keys()):
            lines.append(f"## {section}")
            for fact in by_section[section]:
                lines.append(f"- {fact}")
            lines.append("")

        pruned_memory = "\n".join(lines).strip()
        return pruned_memory, archive

    def score_facts_by_relevance(
        self,
        archive: dict[str, Any],
        query_topics: list[str] | None = None,
    ) -> list[tuple[float, str]]:
        """
        Score archived facts by relevance.

        Query topics: e.g., ["Python", "DevOps", "memory"] — facts matching these score higher.

        Returns:
            List of (score, fact_id) sorted by score (descending).
        """
        if not archive:
            return []

        scored = []
        for fact_id, entry in archive.items():
            # Base score: frequency and merge count
            score = (entry.get("frequency", 0) * 1.5) + (entry.get("merged", 1) * 0.5)

            # Boost recent facts
            if entry.get("last_seen"):
                last_seen = datetime.fromisoformat(entry["last_seen"])
                age_days = (datetime.now() - last_seen).days
                if age_days < 7:
                    score += 20
                elif age_days < 30:
                    score += 10

            # Topic relevance (simple keyword match)
            if query_topics:
                text = f"{fact_id} {entry.get('text', '')}".lower()
                for topic in query_topics:
                    if topic.lower() in text:
                        score += 15

            scored.append((score, fact_id))

        return sorted(scored, key=lambda x: x[0], reverse=True)

    def suggest_fact_to_archive(
        self,
        memory: str,
        archive: dict[str, Any],
    ) -> str | None:
        """
        Return the least relevant fact to archive (for pruning).

        Returns fact_id or None if none available.
        """
        facts = self.parse_facts_from_memory(memory)
        if not facts:
            return None

        # Score in reverse (lowest score = archive first)
        scores = self.score_facts_by_relevance(archive)
        scores.reverse()  # Now lowest scores first

        if scores:
            return scores[0][1]  # fact_id

        return None
