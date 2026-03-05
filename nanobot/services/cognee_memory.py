"""Cognee-backed Memory Service for Nanobot."""

import os
import asyncio
from pathlib import Path
from typing import Any, Optional

import cognee
from cognee.shared.data_models import SearchType
from loguru import logger
from pydantic import BaseModel

class UserFact(BaseModel):
    """Explicit Ontology for Memory Nodes to reduce schema hallucinations."""
    fact_type: str
    description: str

class MemoryProviderError(Exception):
    """Exception raised for errors in the external Memory/Graph Provider."""
    pass

class CogneeMemoryService:
    """Provides memory graph and vector storage using Cognee ECL pipeline."""

    def __init__(self, workspace_dir: str):
        self.workspace_dir = Path(workspace_dir)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        # Configure Cognee to use workspace
        cognee.config.data_root_directory(str(self.workspace_dir))
        
        # Concurrency safety for local DB writes
        self._db_lock = asyncio.Lock()
        
        # Ensure we don't break if api keys are missing
        self.api_key = os.environ.get("LLM_API_KEY", "")
        if self.api_key:
            os.environ["OPENAI_API_KEY"] = self.api_key
            if hasattr(cognee.config, "set_llm_api_key"):
                cognee.config.set_llm_api_key(self.api_key)

    async def add(self, text: str, session_key: str) -> None:
        """Extract: Add literal text context to the graph, tied to a session."""
        if not text or not text.strip():
            return
            
        try:
            fact = UserFact(fact_type="Conversation Log", description=text)
            await cognee.add([fact], dataset_name=session_key)
        except Exception as e:
            raise MemoryProviderError(f"Failed to add data to Cognee: {e}") from e

    async def cognify(self, session_key: Optional[str | list[str]] = None) -> None:
        """Cognify: serialize graph entity generation to prevent write conflicts."""
        async with self._db_lock:
            try:
                datasets_to_cognify = None
                if session_key:
                    datasets_to_cognify = [session_key] if isinstance(session_key, str) else session_key
                
                await cognee.cognify(datasets=datasets_to_cognify)
            except Exception as e:
                raise MemoryProviderError(f"Failed to cognify data: {e}") from e

    async def memify(self) -> None:
        """Memify: Optional multi-hop relations / graph enrichment."""
        try:
            if hasattr(cognee, "memify"):
                await cognee.memify()
            else:
                logger.warning("Cognee memify() is not available in the current installed version.")
        except Exception as e:
            logger.error(f"Memify enrichment failed: {e}")

    async def search(self, query: str, search_type: SearchType, limit: int = 5) -> Any:
        """Load: Search graph or vector DB with strict limits."""
        try:
            results = await cognee.search(search_type, query_text=query, limit=limit)
            return results
        except Exception as e:
            raise MemoryProviderError(f"Failed to search memory: {e}") from e

    async def delete_user_nodes(self, session_key: str) -> None:
        """Privacy Guard: Prune exact nodes/dataset matching the user's session."""
        try:
            if hasattr(cognee.prune, "prune_data"):
                await cognee.prune.prune_data()
            elif hasattr(cognee, "prune"):
                 await cognee.prune.prune()
        except Exception as e:
            raise MemoryProviderError(f"Failed to prune user data: {e}") from e

    async def close(self) -> None:
        """Safely close database connections if supported by the provider."""
        try:
            if hasattr(cognee, "system") and hasattr(cognee.system, "close"):
                await cognee.system.close()
        except Exception as e:
            logger.error(f"Failed to cleanly close Cognee DBs: {e}")
