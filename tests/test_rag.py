import code_chat_rag


def test_version() -> None:

    assert code_chat_rag.__version__ == "0.1.0"

"""Tests for code_chat_rag package."""

from code_chat_rag import CodeIndexer, CodeRAGManager, VectorStoreManager, __version__


def test_package_metadata() -> None:
    """Verify package version export."""
    assert __version__ == "0.1.0"


def test_code_indexer_skeleton() -> None:
    """Verify CodeIndexer initialization and load_and_chunk skeleton."""
    indexer = CodeIndexer(repo_path="/dummy/path")
    assert indexer.repo_path == "/dummy/path"
    assert indexer.load_and_chunk() == []


def test_vector_store_manager_skeleton() -> None:
    """Verify VectorStoreManager initialization, add_chunks, and search skeleton."""
    store = VectorStoreManager(collection_name="test_collection")
    assert store.collection_name == "test_collection"

    # Verify no error on add_chunks call
    store.add_chunks([])

    # Verify search returns empty list
    assert store.search(query="test query", top_k=3) == []


def test_code_rag_manager_skeleton() -> None:
    """Verify CodeRAGManager orchestrator integration."""
    manager = CodeRAGManager(repo_path="/dummy/path")
    assert manager.repo_path == "/dummy/path"

    # Test indexing build
    indexed_count = manager.build_index()
    assert indexed_count == 0

    # Test context retrieval
    results = manager.retrieve_context(query="find function", top_k=5)
    assert results == []
