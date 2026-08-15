"""ベクトルストア機能のテスト."""

from code_chat_rag import VectorStore


def test_vector_store_skeleton() -> None:
    """VectorStore の初期化、add_chunks、および search のスケルトン動作を検証する."""
    store = VectorStore(collection_name="test_collection")
    assert store.collection_name == "test_collection"

    # Verify no error on add_chunks call
    store.add_chunks([])

    # Verify search returns empty list
    assert not store.search(query="test query", top_k=3)
