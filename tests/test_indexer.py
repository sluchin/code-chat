"""RAG インデクサーモジュール（`code_chat_rag.indexer`）のテスト。"""

from code_chat_rag import CodeIndexer


def test_code_indexer_skeleton() -> None:
    """CodeIndexer の初期化および load_and_chunk のスケルトン動作を検証する。"""
    indexer = CodeIndexer(repo_path="/dummy/path")
    assert indexer.repo_path == "/dummy/path"
    assert not indexer.load_and_chunk()
