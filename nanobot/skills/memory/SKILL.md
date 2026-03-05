---
name: memory
description: Three-tier Neuro-Episodic Cognitive Architecture (NECA) with semantic recall.
always: true
---

# Memory

## Structure

- **Tier 1: Working State** — A concise summary of the current task, intent, and progress. Always loaded.
- **Tier 2: Semantic Facts** (`memory/MEMORY.md`) — Long-term facts (preferences, project context, relationships). Always loaded.
- **Tier 3: Episodic Retrieval** (`memory/HISTORY.md`) — Semantic search automatically retrieves the top 3 relevant snippets from your past conversations based on your current turn.

## Search Past Events

While semantic search is automatic, you can still perform manual deep searches:

```bash
grep -i "keyword" memory/HISTORY.md
```

## How to use Memory

- **Write**: For important, static facts, edit `memory/MEMORY.md` directly.
- **Recall**: Just mention a past event; the semantic system will automatically pull the most relevant context into your prompt.
- **Continuity**: The "Working State" summary ensures you never lose track of complex multi-step tasks across conversation boundaries.
