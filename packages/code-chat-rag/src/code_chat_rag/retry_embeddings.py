"""埋め込みの呼び出しに, Gemini API のリトライを加えるモジュール."""

from langchain_core.embeddings import Embeddings

from code_chat_cli.api import call_with_retry


class RetryEmbeddings(Embeddings):
    """別の `Embeddings` を包み, 埋め込みの呼び出しを `call_with_retry` 経由で実行します.

    LangChain の `GoogleGenerativeAIEmbeddings` は, 一時的なエラーをリトライしないため, 検索時と
    インデックス作成時 (バッチごと) の両方で, ここでリトライします.
    """

    def __init__(self, embeddings: Embeddings) -> None:
        """RetryEmbeddings インスタンスを初期化します.

        Args:
            embeddings (Embeddings): 実際に埋め込みを行うインスタンス.

        """
        self.embeddings = embeddings

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """複数の文書を埋め込みます (一時的なエラーはリトライされます).

        Args:
            texts (list[str]): 埋め込む文書のリスト.

        Returns:
            list[list[float]]: 文書ごとの埋め込みベクトル.

        """
        return call_with_retry(self.embeddings.embed_documents, texts)

    def embed_query(self, text: str) -> list[float]:
        """検索クエリを埋め込みます (一時的なエラーはリトライされます).

        Args:
            text (str): 埋め込むクエリ.

        Returns:
            list[float]: 埋め込みベクトル.

        """
        return call_with_retry(self.embeddings.embed_query, text)
