"""Main orchestrator for code-chat RAG pipelines."""

from typing import Any

from code_chat_rag.indexer import CodeIndexer
from code_chat_rag.store import VectorStoreManager


class CodeRAGManager:
    """Facade for repository indexing, search retrieval, and context formatting."""

    def __init__(self, repo_path: str) -> None:
        self.repo_path = repo_path
        self.indexer = CodeIndexer(repo_path)
        self.store = VectorStoreManager()

    def build_index(self) -> int:
        """Parse source code and build the vector search index.

        Returns:
            Number of indexed chunks.
        """
        chunks = self.indexer.load_and_chunk()
        self.store.add_chunks(chunks)
        return len(chunks)

    def retrieve_context(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Search relevant code context for a query."""
        return self.store.search(query, top_k=top_k)
