"""Session management module.

Legacy session storage has been decommissioned in favor of the Cognee
knowledge graph engine. Importing `Session` or `SessionManager` is
disabled until the Cognee integration is completed.
"""

raise ImportError(
	"Legacy session management removed. Install and configure CogneeMemoryService "
	"and update code references to use the new service."
)
