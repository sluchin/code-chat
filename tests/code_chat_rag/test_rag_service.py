# pylint: disable=redefined-outer-name,protected-access
"""`code_chat_rag.rag_service` モジュールのテスト."""

from unittest.mock import MagicMock, patch

import pytest
from code_chat_rag.rag_service import RagService
from langchain_core.documents import Document
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda


@pytest.fixture
def mock_dependencies():
    """VectorStore と ChatGoogleGenerativeAI をモック化する fixture."""
    # RunnableLambda を使い, StrOutputParser が処理できる AIMessage を返すモック LLM を定義
    fake_llm = RunnableLambda(
        lambda prompt: AIMessage(content="hello関数とworld関数が定義されています。")
    )

    with (
        patch("code_chat_rag.rag_service.VectorStore") as mock_vector_store_cls,
        patch(
            "code_chat_rag.rag_service.ChatGoogleGenerativeAI",
            return_value=fake_llm,
        ) as mock_llm_cls,
    ):
        mock_vs_instance = MagicMock()
        mock_vector_store_cls.return_value = mock_vs_instance

        yield {
            "vs_cls": mock_vector_store_cls,
            "vs_inst": mock_vs_instance,
            "llm_cls": mock_llm_cls,
            "fake_llm": fake_llm,
        }


class TestInit:
    """`RagService.__init__` のテスト."""

    def test_init_success(self, mock_dependencies):
        """RagService の初期化処理を検証する."""
        service = RagService(
            output_dir="/dummy/chroma",
            model_name="gemini-3.5-flash",
        )

        assert service.output_dir == "/dummy/chroma"
        mock_dependencies["vs_cls"].assert_called_once_with(output_dir="/dummy/chroma")
        mock_dependencies["llm_cls"].assert_called_once_with(
            model="gemini-3.5-flash",
            temperature=0.0,
        )


class TestIndexRepository:
    """`RagService.index_repository` のテスト."""

    @patch("code_chat_rag.rag_service.Indexer")
    def test_index_repository_success(self, mock_indexer_cls, mock_dependencies):
        """index_repository が正しく Indexer と VectorStore を呼び出すか検証する."""
        # モックの設定
        mock_indexer_instance = MagicMock()
        mock_indexer_instance.load_and_chunk.return_value = [
            {"page_content": "code1", "metadata": {}},
            {"page_content": "code2", "metadata": {}},
        ]
        mock_indexer_cls.return_value = mock_indexer_instance
        mock_dependencies["vs_inst"].add_chunks.return_value = ["id1", "id2"]

        service = RagService(input_dirs=["/dummy/path"])

        # 実行
        count = service.index_repository(input_dirs=["/target/repo"])

        # 検証
        assert count == 2
        mock_indexer_cls.assert_called_once_with(input_dirs=["/target/repo"])
        mock_indexer_instance.load_and_chunk.assert_called_once()
        mock_dependencies["vs_inst"].add_chunks.assert_called_once_with(
            [
                {"page_content": "code1", "metadata": {}},
                {"page_content": "code2", "metadata": {}},
            ]
        )

    @patch("code_chat_rag.rag_service.Indexer")
    def test_index_repository_empty(self, mock_indexer_cls, mock_dependencies):
        """チャンクが空の場合は 0 を返し, add_chunks が呼ばれないことを検証する."""
        mock_indexer_instance = MagicMock()
        mock_indexer_instance.load_and_chunk.return_value = []
        mock_indexer_cls.return_value = mock_indexer_instance

        service = RagService()
        count = service.index_repository(input_dirs=["/target/repo"])

        assert count == 0
        mock_dependencies["vs_inst"].add_chunks.assert_not_called()


class TestGetContext:
    """`RagService.get_context` のテスト."""

    def test_get_context_formats_retrieved_docs_success(self, mock_dependencies):
        """検索結果がファイルパス付きのコンテキスト文字列に整形されるか検証する."""
        retriever = mock_dependencies["vs_inst"].as_retriever.return_value
        retriever.invoke.return_value = [
            Document(page_content="code1", metadata={"source": "a.py"}),
            Document(page_content="code2", metadata={}),
        ]

        context = RagService().get_context("question", k=2)

        mock_dependencies["vs_inst"].as_retriever.assert_called_once_with(k=2)
        retriever.invoke.assert_called_once_with("question")
        assert context == "--- File: a.py ---\ncode1\n\n--- File: Unknown ---\ncode2"


class TestClear:
    """`RagService.clear` のテスト."""

    def test_clear_delegates_to_vector_store_success(self, mock_dependencies):
        """clear が VectorStore の初期化を呼び出すか検証する."""
        RagService().clear()

        mock_dependencies["vs_inst"].clear.assert_called_once_with()


class TestQueryStream:
    """`RagService.query_stream` のテスト."""

    @patch.object(RagService, "_build_chain")
    def test_query_stream_success(self, mock_build_chain):
        """ask_stream メソッドがトークンを逐次生成（ジェネレータ化）するか検証する."""
        mock_chain = MagicMock()
        mock_chain.stream.return_value = iter(["Hello", " ", "World"])
        mock_build_chain.return_value = mock_chain

        service = RagService()
        stream_result = list(service.query_stream("How to run this?", k=3))

        assert stream_result == ["Hello", " ", "World"]
        mock_build_chain.assert_called_once_with(k=3)
        mock_chain.stream.assert_called_once_with("How to run this?")


class TestGetStatus:
    """`RagService.get_status` のテスト."""

    def test_get_status_success(self, mock_dependencies, tmp_path):
        """ステータスにデータベースパスとチャンク数が含まれるか検証する."""
        mock_dependencies["vs_inst"].count.return_value = 7

        status = RagService(output_dir=str(tmp_path)).get_status()

        assert str(tmp_path.resolve()) in status
        assert "総インデックスチャンク数: 7" in status


class TestBuildChain:
    """`RagService._build_chain` のテスト."""

    def test_build_chain_execution_success(self, mock_dependencies):
        """_build_chain で構築された LCEL チェーンの動作と format_docs の実行を検証する."""
        mock_vs = mock_dependencies["vs_inst"]

        # 検索結果として返される Document リストを設定
        retrieved_docs = [
            Document(
                page_content="def hello():\n    print('Hello')",
                metadata={"source": "src/hello.py"},
            ),
            Document(
                page_content="def world():\n    print('World')",
                metadata={"source": "src/world.py"},
            ),
        ]

        # Retriever を RunnableLambda にすることで, 後続の format_docs へ確実に Document リストが渡るようにする
        retriever_calls = []

        def fake_retriever_func(query):
            retriever_calls.append(query)
            return retrieved_docs

        fake_retriever = RunnableLambda(fake_retriever_func)
        mock_vs.as_retriever.return_value = fake_retriever

        # テスト対象の実行
        service = RagService()
        chain = service._build_chain(k=3)

        query = "どのような関数が定義されていますか？"
        result = chain.invoke(query)

        # 検証
        expected_answer = "hello関数とworld関数が定義されています。"
        assert result == expected_answer

        # as_retriever の引数検証
        mock_vs.as_retriever.assert_called_once_with(k=3)

        # Retriever にクエリが渡ったか検証
        assert len(retriever_calls) == 1
        assert retriever_calls[0] == query
