"""RAG サービスおよびベクトルストア統合のテスト."""

from code_chat_rag import CodeRagService, __version__


def test_package_metadata() -> None:
    """パッケージバージョン情報のエクスポートを検証する."""
    assert __version__ == "0.1.0"


def test_code_rag_service_skeleton() -> None:
    """CodeRagService オーケストレーターの統合およびスケルトン動作を検証する."""
    manager = CodeRagService(repo_path="/dummy/path")
    assert manager.repo_path == "/dummy/path"

    # Test indexing build
    indexed_count = manager.build_index()
    assert indexed_count == 0

    # Test context retrieval
    results = manager.retrieve_context(query="find function", top_k=5)
    assert not results
