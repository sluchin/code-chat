"""コード埋め込み用のベクトルストア管理モジュール."""

import logging
from pathlib import Path
from typing import Any

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_google_genai import GoogleGenerativeAIEmbeddings

logger = logging.getLogger(__name__)


class VectorStore:
    """ベクトルデータベースを使用したコードチャンクの保存および検索を処理します."""

    def __init__(
        self,
        persist_directory: str = "./.chroma_db",
        embedding_function: Embeddings | None = None,
    ) -> None:
        self.persist_directory = str(persist_directory)
        # デフォルトは OpenAIEmbeddings (環境変数 OPENAI_API_KEY が必要).
        self.embeddings = embedding_function or GoogleGenerativeAIEmbeddings(
            model="gemini-flash-latest"
        )
        self._db: Chroma | None = None

    def _get_db(self) -> Chroma:
        """Chromaデータベースインスタンスを取得または初期化します."""
        path = Path(self.persist_directory)
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning("ディレクトリ '%s' の作成に失敗しました: %s", path, e)

        if not path.exists():
            raise FileNotFoundError(f"ディレクトリのパスが存在しません: {path}")

        if self._db is None:
            self._db = Chroma(
                persist_directory=str(path),
                embedding_function=self.embeddings,
            )
        return self._db

    def add_chunks(self, chunks: list[dict[str, Any]]) -> list[str]:
        """チャンクの辞書データをベクトルデータベースに保存します.

        Args:
            chunks: 'page_content' と 'metadata' を含む辞書のリスト.

        Returns:
            生成されたドキュメントIDのリスト.
        """
        if not chunks:
            return []

        # 辞書型データを LangChain の Document オブジェクトに変換
        documents = [
            Document(
                page_content=chunk["page_content"],
                metadata=chunk.get("metadata", {}),
            )
            for chunk in chunks
        ]

        # Chroma DB にドキュメントを追加 (自動的に永続化されます)
        db = self._get_db()
        ids = db.add_documents(documents)
        return ids

    def as_retriever(self, search_type: str = "similarity", k: int = 4):
        """検索実行用のリトリーバーインターフェースを返します."""
        db = self._get_db()
        return db.as_retriever(search_type=search_type, search_kwargs={"k": k})
