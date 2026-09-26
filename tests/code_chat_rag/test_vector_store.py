# pylint: disable=redefined-outer-name,protected-access
"""`code_chat_rag.vector_store` モジュールのテスト."""

from unittest.mock import MagicMock, patch

import pytest
from code_chat_rag.retry_embeddings import RetryEmbeddings
from code_chat_rag.vector_store import VectorStore
from langchain_core.documents import Document


@pytest.fixture
def mock_embedding():
    """GoogleGenerativeAIEmbeddings のモック fixture."""
    return MagicMock()


class TestInit:
    """`VectorStore.__init__` のテスト."""

    def test_init_success(self, mock_embedding):
        """VectorStore の初期化処理を検証する."""
        store = VectorStore(
            output_dir="/dummy/path",
            embedding_function=mock_embedding,
        )
        assert store.output_dir == "/dummy/path"
        assert isinstance(store.embeddings, RetryEmbeddings)
        assert store.embeddings.embeddings == mock_embedding
        assert store._db is None


class TestAddChunks:
    """`VectorStore.add_chunks` のテスト."""

    @patch("code_chat_rag.vector_store.Chroma")
    def test_add_chunks_success(self, mock_chroma_cls, mock_embedding, tmp_path):
        """チャンクデータ（辞書のリスト）が正常に Document 化され Chroma に保存されるか検証する."""
        # ダミーの保存先ディレクトリを作成
        persist_dir = tmp_path / ".chroma_db"
        persist_dir.mkdir()

        # Chroma インスタンスのモック設定
        mock_chroma_instance = MagicMock()
        mock_chroma_instance.add_documents.return_value = ["id1", "id2"]
        mock_chroma_cls.return_value = mock_chroma_instance

        store = VectorStore(
            output_dir=str(persist_dir),
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
            embedding_function=store.embeddings,
        )

        # Document オブジェクトとして正しく変換されて渡されたか確認
        expected_docs = [
            Document(page_content="print('hello')", metadata={"source": "main.py"}),
            Document(page_content="def foo(): pass", metadata={"source": "utils.py"}),
        ]
        mock_chroma_instance.add_documents.assert_called_once_with(
            expected_docs, batch_size=32
        )

    def test_add_chunks_empty(self, mock_embedding):
        """空のチャンクリストを渡した場合に空配列が返され DB が呼び出されないことを検証する."""
        store = VectorStore(
            output_dir="/dummy/path",
            embedding_function=mock_embedding,
        )
        assert store.add_chunks([]) == []


class TestAsRetriever:
    """`VectorStore.as_retriever` のテスト."""

    @patch("code_chat_rag.vector_store.Chroma")
    def test_as_retriever_success(self, mock_chroma_cls, mock_embedding, tmp_path):
        """リトリーバーインターフェースが正しく取得できるか検証する."""
        persist_dir = tmp_path / ".chroma_db"
        persist_dir.mkdir()

        mock_chroma_instance = MagicMock()
        mock_retriever = MagicMock()
        mock_chroma_instance.as_retriever.return_value = mock_retriever
        mock_chroma_cls.return_value = mock_chroma_instance

        store = VectorStore(
            output_dir=str(persist_dir),
            embedding_function=mock_embedding,
        )

        retriever = store.as_retriever(search_type="similarity", k=5)

        assert retriever == mock_retriever
        mock_chroma_instance.as_retriever.assert_called_once_with(
            search_type="similarity",
            search_kwargs={"k": 5},
        )


class TestCount:
    """`VectorStore.count` のテスト."""

    @patch("code_chat_rag.vector_store.Chroma")
    def test_count_success(self, mock_chroma_cls, mock_embedding, tmp_path):
        """登録されているドキュメントの件数が返るか検証する."""
        persist_dir = tmp_path / ".chroma_db"
        persist_dir.mkdir()
        mock_chroma_cls.return_value._collection.count.return_value = 7

        store = VectorStore(
            output_dir=str(persist_dir), embedding_function=mock_embedding
        )

        assert store.count() == 7


class TestSearchDebug:
    """`VectorStore.search_debug` のテスト."""

    @patch("code_chat_rag.vector_store.Chroma")
    def test_search_debug_returns_scored_results_success(
        self, mock_chroma_cls, mock_embedding, tmp_path
    ):
        """スコア付き検索の結果がそのまま返されるか検証する."""
        doc = Document(page_content="print('hello')", metadata={"source": "main.py"})
        mock_chroma_cls.return_value.similarity_search_with_score.return_value = [
            (doc, 0.25)
        ]
        store = VectorStore(output_dir=str(tmp_path), embedding_function=mock_embedding)

        results = store.search_debug("hello", k=1)

        assert results == [(doc, 0.25)]
        mock_chroma_cls.return_value.similarity_search_with_score.assert_called_once_with(
            "hello", k=1
        )


class TestClear:
    """`VectorStore.clear` のテスト."""

    def test_clear_deletes_all_documents_success(self, mock_embedding):
        """コレクション内の全ドキュメントが削除されるか検証する."""
        store = VectorStore(embedding_function=mock_embedding)
        store._db = MagicMock()
        store._db._collection.get.return_value = {"ids": ["1", "2"]}

        store.clear()

        store._db.delete.assert_called_once_with(ids=["1", "2"])

    def test_clear_reraises_errors_failure(self, mock_embedding):
        """削除中の例外がログ出力の上で再送出されるか検証する."""
        store = VectorStore(embedding_function=mock_embedding)
        store._db = MagicMock()
        store._db._collection.get.side_effect = RuntimeError("db error")

        with pytest.raises(RuntimeError, match="db error"):
            store.clear()

    def test_clear_with_empty_collection_or_uninitialized_db(self, mock_embedding):
        """空のコレクションや未初期化の DB では削除処理を行わないか検証する."""
        store = VectorStore(embedding_function=mock_embedding)
        store.clear()  # _db 未初期化

        store._db = MagicMock()
        store._db._collection.get.return_value = {"ids": []}
        store.clear()

        store._db.delete.assert_not_called()


class TestGetDb:
    """`VectorStore._get_db` のテスト."""

    def test_get_db_file_not_found_failure(self):
        """存在しないディレクトリを指定した場合に FileNotFoundError が発生するか検証する."""
        store = VectorStore(output_dir="/non_existent_directory_path_12345")
        with pytest.raises(FileNotFoundError):
            store._get_db()
