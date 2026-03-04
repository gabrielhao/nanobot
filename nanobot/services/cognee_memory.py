"""Cognee memory service shim for knowledge graph operations.

This is a minimal, test-oriented implementation that simulates a Cognee
knowledge graph backed by SQLite. It provides the required API:

- add(doc: dict)
- cognify(doc: dict) -> dict
- search(query: str, search_type=SearchType.GRAPH_COMPLETION) -> list[dict]

Persistence is implemented via SQLite (`cognee_store.db`) to survive restarts.
No `.json` or `.txt` files are written by this module.

Both synchronous (CogneeMemoryService) and asynchronous (CogneeMemoryServiceAsync)
versions are provided. Prefer the async version for event loop contexts.
"""

from __future__ import annotations

import sqlite3
import json
import threading
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta


class SearchType(Enum):
    GRAPH_COMPLETION = "graph_completion"


@dataclass
class CogneeResult:
    id: int
    content: str
    metadata: dict
    updated_at: datetime


class CogneeMemoryService:
    """Minimal Cognee-like service backed by SQLite.

    Tables:
      - nodes(id INTEGER PRIMARY KEY, content TEXT, metadata TEXT)
      - edges(src INT, dst INT, label TEXT)

    Simple cognify: extracts tokens and stores them as metadata.keywords.
    """

    def __init__(self, workspace: Path | None = None, db_name: str = "cognee_store.db"):
        self.workspace = Path(workspace) if workspace else Path.cwd()
        self.db_path = self.workspace / db_name
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            # Enable foreign keys for referential integrity
            cur.execute("PRAGMA foreign_keys = ON")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS nodes (
                  id INTEGER PRIMARY KEY,
                  content TEXT NOT NULL,
                  metadata TEXT DEFAULT '{}',
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS edges (
                  id INTEGER PRIMARY KEY,
                  src INTEGER NOT NULL,
                  dst INTEGER NOT NULL,
                  label TEXT DEFAULT '',
                  FOREIGN KEY (src) REFERENCES nodes(id) ON DELETE CASCADE,
                  FOREIGN KEY (dst) REFERENCES nodes(id) ON DELETE CASCADE,
                  UNIQUE(src, dst, label)
                )
                """
            )
            # Add indexes for faster lookups
            cur.execute("CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst)")
            self._conn.commit()

    def add(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> int:
        """Add a node to the graph and return its id."""
        if not content:
            raise ValueError("Content cannot be empty")
        metadata = metadata or {}
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("INSERT INTO nodes (content, metadata) VALUES (?, ?)", (content, json.dumps(metadata, ensure_ascii=False)))
            node_id = cur.lastrowid
            self._conn.commit()
            return node_id

    def link(self, src: int, dst: int, label: str = "relates_to") -> None:
        """Create an edge between two nodes with referential integrity.
        
        Raises ValueError if either node does not exist.
        """
        with self._lock:
            try:
                cur = self._conn.cursor()
                # Verify both nodes exist before creating edge
                cur.execute("SELECT id FROM nodes WHERE id = ?", (src,))
                if not cur.fetchone():
                    raise ValueError(f"Source node {src} does not exist")
                
                cur.execute("SELECT id FROM nodes WHERE id = ?", (dst,))
                if not cur.fetchone():
                    raise ValueError(f"Destination node {dst} does not exist")
                
                # Insert edge with foreign key constraint
                cur.execute("INSERT OR IGNORE INTO edges (src, dst, label) VALUES (?, ?, ?)", (src, dst, label))
                self._conn.commit()
            except sqlite3.IntegrityError as e:
                self._conn.rollback()
                raise ValueError(f"Could not create edge: {e}")
            except Exception as e:
                self._conn.rollback()
                raise

    def cognify(self, node_id: int) -> Dict[str, Any]:
        """Process a node to extract metadata (keywords) and persist.

        This simulates an LLM-driven cognify operation. It returns the updated metadata.
        Extracts meaningful keywords (not just any word) using TF-based scoring.
        """
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT content, metadata FROM nodes WHERE id = ?", (node_id,))
            row = cur.fetchone()
            if not row:
                raise KeyError("node not found")
            content, meta_json = row
            try:
                meta = json.loads(meta_json or "{}")
            except Exception:
                meta = {}

            # Improved keyword extraction: filter common words, score by frequency
            stop_words = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "is", "are", "be", "was", "were", "been", "have", "has", "do", "does", "did", "will", "would", "could", "should", "may", "might", "must", "can", "this", "that", "these", "those", "i", "you", "he", "she", "it", "we", "they", "over", "from", "by", "as", "with", "if", "about", "what", "which", "who", "when", "where", "why", "how"}
            tokens = [t.strip().lower() for t in content.replace("\n", " ").split() if len(t) > 2 and t.isalpha()]
            
            # Score tokens by frequency (TF)
            freq = {}
            for token in tokens:
                if token not in stop_words:
                    freq[token] = freq.get(token, 0) + 1
            
            # Take top 10 by frequency
            keywords = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:10]
            keywords = [k for k, _ in keywords]
            
            meta["keywords"] = keywords
            cur.execute("UPDATE nodes SET metadata = ?, updated_at = ? WHERE id = ?", (json.dumps(meta, ensure_ascii=False), datetime.now().strftime('%Y-%m-%d %H:%M:%S'), node_id))
            self._conn.commit()
            meta["updated_at"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            return meta

    def search(self, query: str, search_type: SearchType = SearchType.GRAPH_COMPLETION, top_k: int = 5, max_chars: int = 4000) -> List[CogneeResult]:
        """Search the graph for nodes matching the query keywords with temporal decay and budget."""
        if not query or not query.strip():
            return []
            
        qtokens = [t.strip().lower() for t in query.split() if t.isalpha() and len(t) > 2]
        
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT id, content, metadata, updated_at FROM nodes")
            results: List[Tuple[float, CogneeResult]] = []
            rows = cur.fetchall()
            
            for r in rows:
                nid, content, md, updated_at_str = r
                try:
                    meta = json.loads(md or "{}")
                except Exception:
                    meta = {}
                
                keywords = meta.get("keywords", [])
                
                # Base relevance score
                if not qtokens:
                    relevance = 1.0 if query.lower() in content.lower() else 0.0
                else:
                    matches = sum(1 for t in qtokens if t in keywords or t in content.lower())
                    relevance = (matches / len(qtokens)) if matches > 0 else 0.0

                # Apply temporal decay
                if relevance > 0:
                    try:
                        updated_at = datetime.strptime(updated_at_str, '%Y-%m-%d %H:%M:%S')
                        days_old = (datetime.now() - updated_at).days
                        decay = max(0.5, 1.0 - (days_old / 30.0))
                        relevance *= decay
                    except (ValueError, TypeError):
                        updated_at = datetime.now()

                if relevance > 0:
                    results.append((relevance, CogneeResult(id=nid, content=content, metadata=meta, updated_at=updated_at)))
            
            results.sort(key=lambda x: x[0], reverse=True)
            
            # Apply budget and top_k to initial results
            budgeted_top = []
            total_chars = 0
            for _, res in results:
                if len(budgeted_top) >= top_k:
                    break
                if total_chars + len(res.content) <= max_chars:
                    budgeted_top.append(res)
                    total_chars += len(res.content)
            
            top = budgeted_top
            
            if search_type == SearchType.GRAPH_COMPLETION and top:
                expanded: List[CogneeResult] = []
                seen_ids: set = {node.id for node in top}
                expanded.extend(top)
                
                for node in top:
                    cur.execute("SELECT dst FROM edges WHERE src = ? LIMIT 50", (node.id,))
                    neighbor_ids = [r[0] for r in cur.fetchall()]
                    cur.execute("SELECT src FROM edges WHERE dst = ? LIMIT 50", (node.id,))
                    neighbor_ids.extend([r[0] for r in cur.fetchall()])
                    
                    for dst in neighbor_ids:
                        if dst not in seen_ids:
                            cur.execute("SELECT id, content, metadata FROM nodes WHERE id = ?", (dst,))
                            rr = cur.fetchone()
                            if rr:
                                seen_ids.add(dst)
                                meta_n = json.loads(rr[2] or "{}")
                                expanded.append(CogneeResult(id=rr[0], content=rr[1], metadata=meta_n))

                # Apply budget to the final expanded list
                final_expanded = []
                total_chars_expanded = 0
                for res in expanded:
                    if total_chars_expanded + len(res.content) > max_chars:
                        break
                    final_expanded.append(res)
                    total_chars_expanded += len(res.content)
                
                return final_expanded[:top_k * 2]
            
            return top

    def delete_user_nodes(self, user_id: str) -> int:
        """Delete all nodes associated with a user_id."""
        with self._lock:
            cur = self._conn.cursor()
            # Find nodes where metadata contains user_id
            cur.execute("SELECT id, metadata FROM nodes")
            to_delete = []
            for nid, meta_json in cur.fetchall():
                meta = json.loads(meta_json or "{}")
                if meta.get("user_id") == user_id:
                    to_delete.append(nid)
            
            for nid in to_delete:
                cur.execute("DELETE FROM nodes WHERE id = ?", (nid,))
            
            self._conn.commit()
            return len(to_delete)

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


class CogneeMemoryServiceAsync:
    """Async-safe Cognee service using thread pool for DB I/O."""
    
    def __init__(self, workspace: Path | None = None, db_name: str = "cognee_store.db", max_workers: int = 4):
        self._sync_service = CogneeMemoryService(workspace=workspace, db_name=db_name)
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="cognee-db")
    
    async def add(self, content: str, metadata: Optional[Dict[str, Any]] = None) -> int:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, self._sync_service.add, content, metadata)
    
    async def link(self, src: int, dst: int, label: str = "relates_to") -> None:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, self._sync_service.link, src, dst, label)
    
    async def cognify(self, node_id: int) -> Dict[str, Any]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, self._sync_service.cognify, node_id)
    
    async def search(self, query: str, search_type: SearchType = SearchType.GRAPH_COMPLETION, top_k: int = 5, max_chars: int = 4000) -> List[CogneeResult]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, self._sync_service.search, query, search_type, top_k, max_chars)
    
    async def forget(self, query: str) -> int:
        """Forget (delete) nodes matching a query."""
        results = await self.search(query, top_k=100)
        loop = asyncio.get_event_loop()
        
        def _delete_ids(ids):
            with self._sync_service._lock:
                cur = self._sync_service._conn.cursor()
                for nid in ids:
                    cur.execute("DELETE FROM nodes WHERE id = ?", (nid,))
                self._sync_service._conn.commit()
                return len(ids)
        
        return await loop.run_in_executor(self._executor, _delete_ids, [r.id for r in results])

    async def delete_user_nodes(self, user_id: str) -> int:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, self._sync_service.delete_user_nodes, user_id)
    
    async def close(self) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self._executor, self._sync_service.close)
        self._executor.shutdown(wait=True)
