"""`code_chat_rag.retry_embeddings` モジュールのテスト."""

from unittest.mock import MagicMock

import pytest
from google.genai.errors import APIError

from code_chat_rag.retry_embeddings import RetryEmbeddings


def _unavailable():
    """503 の APIError を作成する."""
    return APIError(503, {"error": {"code": 503, "status": "UNAVAILABLE"}})


class TestEmbedDocuments:
    """`RetryEmbeddings.embed_documents` のテスト."""

    def test_embed_documents_success(self):
        """内側の Embeddings の結果が, そのまま返るか検証する."""
        inner = MagicMock()
        inner.embed_documents.return_value = [[0.1], [0.2]]

        assert RetryEmbeddings(inner).embed_documents(["a", "b"]) == [[0.1], [0.2]]
        inner.embed_documents.assert_called_once_with(["a", "b"])

    def test_embed_documents_retry_exception(self):
        """一時的なエラーは, リトライされて成功するか検証する."""
        inner = MagicMock()
        inner.embed_documents.side_effect = [_unavailable(), [[0.1]]]

        assert RetryEmbeddings(inner).embed_documents(["a"]) == [[0.1]]
        assert inner.embed_documents.call_count == 2

    def test_embed_documents_non_retryable_failure(self):
        """リトライ対象外のエラーは, リトライせずに送出されるか検証する."""
        inner = MagicMock()
        inner.embed_documents.side_effect = ValueError("bad")

        with pytest.raises(ValueError):
            RetryEmbeddings(inner).embed_documents(["a"])
        assert inner.embed_documents.call_count == 1


class TestEmbedQuery:
    """`RetryEmbeddings.embed_query` のテスト."""

    def test_embed_query_success(self):
        """内側の Embeddings の結果が, そのまま返るか検証する."""
        inner = MagicMock()
        inner.embed_query.return_value = [0.1]

        assert RetryEmbeddings(inner).embed_query("q") == [0.1]
        inner.embed_query.assert_called_once_with("q")

    def test_embed_query_retry_exception(self):
        """一時的なエラーは, LangChain が包んだ場合も, リトライされて成功するか検証する."""
        wrapped = RuntimeError("wrapped")
        wrapped.__cause__ = _unavailable()
        inner = MagicMock()
        inner.embed_query.side_effect = [wrapped, [0.1]]

        assert RetryEmbeddings(inner).embed_query("q") == [0.1]
        assert inner.embed_query.call_count == 2
