# pylint: disable=redefined-outer-name
"""`code_chat_rag.vector_store` モジュールのテスト."""

from unittest.mock import MagicMock, patch

import pytest
from code_chat_rag.vector_store import VectorStore
from langchain_core.documents import Document


@pytest.fixture
def mock_embedding():
    """GoogleGenerativeAIEmbeddings のモック fixture."""
    return MagicMock()


# pylint: disable=protected-access
def test_vector_store_init(mock_embedding):
    """VectorStore の初期化処理を検証する."""
    store = VectorStore(
        persist_directory="/dummy/path",
        embedding_function=mock_embedding,
    )
    assert store.persist_directory == "/dummy/path"
    assert store.embeddings == mock_embedding
    assert store._db is None


# pylint: disable=protected-access
def test_get_db_file_not_found():
    """存在しないディレクトリを指定した場合に FileNotFoundError が発生するか検証する."""
    store = VectorStore(persist_directory="/non_existent_directory_path_12345")
    with pytest.raises(FileNotFoundError):
        store._get_db()


@patch("code_chat_rag.vector_store.Chroma")
def test_add_chunks_success(mock_chroma_cls, mock_embedding, tmp_path):
    """チャンクデータ（辞書のリスト）が正常に Document 化され Chroma に保存されるか検証する."""
    # ダミーの保存先ディレクトリを作成
    persist_dir = tmp_path / "chroma_db"
    persist_dir.mkdir()

    # Chroma インスタンスのモック設定
    mock_chroma_instance = MagicMock()
    mock_chroma_instance.add_documents.return_value = ["id1", "id2"]
    mock_chroma_cls.return_value = mock_chroma_instance

    store = VectorStore(
        persist_directory=str(persist_dir),
        embedding_function=mock_embedding,
    )

    chunks = [
        {"page_content": "print('hello')", "metadata": {"source": "main.py"}},
        {"page_content": "def foo(): pass", "metadata": {"source": "utils.py"}},
    ]

    # 実行
    ids = store.add_chunks(chunks)

    # 検証
    assert ids == ["id1", "id2"]
    mock_chroma_cls.assert_called_once_with(
        persist_directory=str(persist_dir),
        embedding_function=mock_embedding,
    )

    # Document オブジェクトとして正しく変換されて渡されたか確認
    expected_docs = [
        Document(page_content="print('hello')", metadata={"source": "main.py"}),
        Document(page_content="def foo(): pass", metadata={"source": "utils.py"}),
    ]
    mock_chroma_instance.add_documents.assert_called_once_with(expected_docs)


def test_add_chunks_empty(mock_embedding):
    """空のチャンクリストを渡した場合に空配列が返され DB が呼び出されないことを検証する."""
    store = VectorStore(
        persist_directory="/dummy/path",
        embedding_function=mock_embedding,
    )
    assert store.add_chunks([]) == []


@patch("code_chat_rag.vector_store.Chroma")
def test_as_retriever(mock_chroma_cls, mock_embedding, tmp_path):
    """リトリーバーインターフェースが正しく取得できるか検証する."""
    persist_dir = tmp_path / "chroma_db"
    persist_dir.mkdir()

    mock_chroma_instance = MagicMock()
    mock_retriever = MagicMock()
    mock_chroma_instance.as_retriever.return_value = mock_retriever
    mock_chroma_cls.return_value = mock_chroma_instance

    store = VectorStore(
        persist_directory=str(persist_dir),
        embedding_function=mock_embedding,
    )

    retriever = store.as_retriever(search_type="similarity", k=5)

    assert retriever == mock_retriever
    mock_chroma_instance.as_retriever.assert_called_once_with(
        search_type="similarity",
        search_kwargs={"k": 5},
    )
