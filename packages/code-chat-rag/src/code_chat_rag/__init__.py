"""code-chat-rag package."""

from code_chat_rag.indexer import CodeIndexer
from code_chat_rag.service import CodeRagService
from code_chat_rag.vector_store import VectorStore

__version__ = "0.1.0"

__all__ = [
    "CodeIndexer",
    "CodeRagService",
    "VectorStore",
    "__version__",
]
