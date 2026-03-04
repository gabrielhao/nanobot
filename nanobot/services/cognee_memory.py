"""Cognee-backed memory service for nanobot.

This module integrates the Cognee ECL (Extract, Cognify, Load) pipeline with
nanobot's session model. It is intentionally thin and fully async so it can
be exercised easily in tests and swapped to different Cognee backends.
"""

from __future__ import annotations

from typing import Any, Iterable, List, Mapping, Sequence

import asyncio
import cognee
from cognee import SearchType
from loguru import logger


class CogneeMemoryError(RuntimeError):
    """Domain-specific error used when Cognee operations fail."""


class CogneeMemoryService:
    """High-level interface for using Cognee as nanobot's long-term memory.

    Responsibilities:
    - Ingest session messages into a Cognee dataset (ECL: add → cognify → memify).
    - Run GRAPH_COMPLETION searches for graph-aware memory retrieval.
    - Provide a privacy guard to delete user-specific graph nodes.
    """

    def __init__(self, *, dataset_name: str = "main_dataset") -> None:
        self.dataset_name = dataset_name
        # Serialize ECL operations per dataset to avoid overlapping memify/cognify runs.
        self._ecl_lock = asyncio.Lock()

    # -------------------------------------------------------------------------
    # Ingestion / ECL pipeline
    # -------------------------------------------------------------------------

    async def ingest_session_messages(
        self,
        session_key: str,
        messages: Sequence[Mapping[str, Any]],
    ) -> None:
        """Ingest a slice of session messages into the Cognee knowledge graph.

        This performs a minimal ECL pipeline:
        1. Extract: Filter messages down to unique, non-empty text contents.
        2. Load:   Call cognee.add(...) once per unique text, tagging the dataset.
        3. Cognify: Build / update the knowledge graph for that dataset.
        4. Memify:  Run enrichment pipelines on the updated graph.

        Any upstream error is wrapped in CogneeMemoryError so callers can handle
        failures gracefully without leaking Cognee's internal exceptions.
        """
        # Step 1: Extract non-empty message contents along with basic metadata.
        contents: List[tuple[str, Mapping[str, Any]]] = []
        for msg in messages:
            text = (msg.get("content") or "").strip()  # type: ignore[arg-type]
            if not text:
                continue
            contents.append((text, msg))

        # Deduplicate while preserving order.
        seen: set[str] = set()
        unique_contents: List[tuple[str, Mapping[str, Any]]] = []
        for text, msg in contents:
            if text in seen:
                continue
            seen.add(text)
            unique_contents.append((text, msg))

        if not unique_contents:
            # Nothing to ingest; return silently.
            return

        try:
            async with self._ecl_lock:
                # Step 2: Load via cognee.add (can be called multiple times).
                for text, msg in unique_contents:
                    await cognee.add(
                        data=text,
                        dataset=self.dataset_name,
                        metadata={
                            "session_key": session_key,
                            "role": msg.get("role"),
                            "timestamp": msg.get("timestamp"),
                            "channel": msg.get("channel"),
                            "user_id": msg.get("user_id"),
                        },
                    )

                # Step 3: Build / update graph.
                await cognee.cognify(datasets=[self.dataset_name])

                # Step 4: Enrich existing graph via memify (default pipeline).
                await cognee.memify(datasets=[self.dataset_name])

        except Exception as exc:  # pragma: no cover - error path covered via tests
            logger.exception("Cognee ingest failed for session %s", session_key)
            raise CogneeMemoryError(f"Ingest failed: {exc}") from exc

    # -------------------------------------------------------------------------
    # Retrieval (GRAPH_COMPLETION)
    # -------------------------------------------------------------------------

    async def search_graph_completion(
        self,
        query_text: str,
        session_key: str,
        *,
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        """Run a GRAPH_COMPLETION-style query against the Cognee graph.

        Returns a list of dictionaries with:
        - answer:  LLM-backed natural language answer.
        - edges:   List of {src, dst, rel} edges representing relationships.
        """
        try:
            results: Iterable[Any] = await cognee.search(
                query_text=query_text,
                search_type=SearchType.GRAPH_COMPLETION,
                datasets=[self.dataset_name],
                session_id=session_key,
                top_k=top_k,
            )
        except Exception as exc:  # pragma: no cover - exercised via other tests
            logger.exception("Cognee search failed for session %s", session_key)
            raise CogneeMemoryError(f"Search failed: {exc}") from exc

        out: list[dict[str, Any]] = []

        for item in results:
            # Best-effort extraction of fields from Cognee result objects.
            answer = getattr(item, "answer", None) or getattr(item, "completion", None)
            if answer is None:
                answer = str(item)

            nodes = getattr(item, "nodes", []) or []
            raw_edges = getattr(item, "edges", []) or []

            edges: list[dict[str, str]] = []
            for edge in raw_edges:
                src = getattr(edge, "src", None) or getattr(edge, "source", None)
                dst = getattr(edge, "dst", None) or getattr(edge, "target", None)
                rel = getattr(edge, "rel", None) or getattr(edge, "relation", None)
                if not (src and dst and rel):
                    continue
                edges.append({"src": str(src), "dst": str(dst), "rel": str(rel)})

            out.append(
                {
                    "answer": answer,
                    "nodes": nodes,
                    "edges": edges,
                }
            )

        return out

    # -------------------------------------------------------------------------
    # Privacy guard
    # -------------------------------------------------------------------------

    async def delete_user_nodes(self, user_id: str) -> None:
        """Delete all nodes and edges associated with a given user ID.

        The exact semantics depend on Cognee's backend; here we forward the
        user_id and dataset name to a dedicated delete function that can be
        implemented server-side.
        """
        try:
            await cognee.delete_nodes(dataset=self.dataset_name, user_id=user_id)
        except Exception as exc:  # pragma: no cover - exercised via dedicated tests
            logger.exception("Cognee delete_nodes failed for user_id=%s", user_id)
            raise CogneeMemoryError(f"Delete failed: {exc}") from exc

