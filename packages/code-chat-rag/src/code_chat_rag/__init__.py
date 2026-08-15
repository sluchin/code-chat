"""code-chat-rag package."""

from code_chat_rag.indexer import CodeIndexer
from code_chat_rag.service import CodeRagService
from code_chat_rag.store import VectorStoreManager

__version__ = "0.1.0"

__all__ = [
    "CodeIndexer",
    "CodeRagService",
    "VectorStoreManager",
    "__version__",
]
