"""コード埋め込み用のベクトルストア管理モジュール."""

import logging
from pathlib import Path
from typing import Any

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStoreRetriever
from langchain_google_genai import GoogleGenerativeAIEmbeddings

logger = logging.getLogger(__name__)


class VectorStore:
    """ベクトルデータベースを使用したコードチャンクの保存および検索を処理します."""

    def __init__(
        self,
        output_dir: str = "./.chroma_db",
        embedding_function: Embeddings | None = None,
    ) -> None:
        """VectorStore インスタンスを初期化します.

        Args:
            output_dir: データベースの永続化先ディレクトリパス.
            embedding_function: 使用する埋め込みモデル. 未指定時は GoogleGenerativeAIEmbeddings を使用.

        """
        self.output_dir = str(output_dir)
        self.embeddings = embedding_function or GoogleGenerativeAIEmbeddings(
            model="gemini-embedding-001"
        )
        self._db: Chroma | None = None

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
        ids = db.add_documents(documents, batch_size=32)
        return ids

    def as_retriever(
        self, search_type: str = "similarity", k: int = 4
    ) -> VectorStoreRetriever:
        """検索実行用のリトリーバーインターフェースを返します.

        Args:
            search_type (str, optional): 検索タイプ (例: "similarity", "mmr"). Defaults to "similarity".
            k (int, optional): 検索結果として取得する上位ドキュメント数. Defaults to 4.

        Returns:
            VectorStoreRetriever: 設定されたリトリーバーインスタンス.

        """
        db = self._get_db()
        return db.as_retriever(search_type=search_type, search_kwargs={"k": k})

    def count(self) -> int:
        """データベースに登録されているドキュメントの総件数を返します.

        Returns:
            int: 登録されているドキュメントの総件数.

        """
        db = self._get_db()
        # pylint: disable=protected-access
        return db._collection.count()

    def search_debug(self, query: str, k: int = 4) -> list[tuple[Document, float]]:
        """検索スコア (距離) 付きでドキュメントを取得するデバッグ用メソッド.

        Args:
            query (str): 検索クエリ文字列.
            k (int, optional): 取得する上位ドキュメント数. Defaults to 4.

        Returns:
            list[tuple[Document, float]]: ドキュメントとスコアのタプルのリスト.

        """
        db = self._get_db()
        # 類似度スコア (距離) 付きで上位k件を取得
        results = db.similarity_search_with_score(query, k=k)
        for doc, score in results:
            logger.info(
                "Score (Distance): %f | Content: %s...",
                score,
                doc.page_content[:50].replace("\n", " "),
            )
        return results

    def clear(self) -> None:
        """VectorStore (Chroma DB コレクション) 内のすべてのデータを削除して初期化します."""
        try:
            logger.info("VectorStore のデータをクリアしています...")

            if self._db is not None:
                # LangChain の Chroma オブジェクトから全件削除
                # コレクション内の全ドキュメント ID を取得して delete を実行
                # pylint: disable=protected-access
                all_data = self._db._collection
                all_ids = all_data.get()["ids"]
                if all_ids:
                    self._db.delete(ids=all_ids)
                    logger.info("%d 件のチャンクを削除しました", len(all_ids))

            logger.info("VectorStore のクリアが完了しました")
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("VectorStore のクリア処理中にエラーが発生しました")
            raise

    def _get_db(self) -> Chroma:
        """Chromaデータベースインスタンスを取得または初期化します.

        Returns:
            Chroma: 初期化されたChromaデータベースインスタンス.

        Raises:
            FileNotFoundError: ディレクトリのパスが存在しない, または作成できなかった場合.

        """
        path = Path(self.output_dir)
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning("ディレクトリ '%s' の作成に失敗しました: %s", path, e)

        if not path.exists():
            raise FileNotFoundError(f"ディレクトリのパスが存在しません: {path}")

        logger.info("Vector DB: %s", path)

        if self._db is None:
            self._db = Chroma(
                persist_directory=str(path),
                embedding_function=self.embeddings,
            )
        return self._db
