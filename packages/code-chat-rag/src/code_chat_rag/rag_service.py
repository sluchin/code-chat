"""コードRAG操作のための高レベルサービスインターフェース."""

from pathlib import Path

from langchain_core.documents import Document

from code_chat_lib.logger import get_logger
from code_chat_rag.indexer import Indexer
from code_chat_rag.vector_store import VectorStore

logger = get_logger(__name__)


class RagService:
    """インデックスの作成, 検索 (関連するコードの取得) を調整するサービスレイヤー."""

    def __init__(
        self,
        input_dirs: list[str] | None = None,
        output_dir: str = "./.chroma_db",
    ) -> None:
        """RagServiceのインスタンスを初期化します.

        Args:
            input_dirs (list[str] | None): 対象のコードリポジトリへのパス.
            output_dir (str): ベクトルストアの永続化先ディレクトリ.

        """
        self.input_dirs = input_dirs
        self.output_dir = output_dir
        self.vector_store = VectorStore(output_dir=output_dir)
        doc_count = self.vector_store.count()
        logger.info("RAG Vector DB: %s", output_dir)
        logger.info("RAG DB 登録ドキュメント数: %d 件", doc_count)

    def index_repository(self, input_dirs: list[str], update_only: bool = False) -> int:
        """コードリポジトリを読み込み, チャンク化してVectorStoreに保存します.

        Args:
            input_dirs: コードリポジトリディレクトリへのパス.
            update_only: True の場合は, 読み込んだファイルの既存のチャンクを置き換えて追加し (他のファイルのデータは残す), False の場合は初期化して全件再作成します.

        Returns:
            インデックスされたチャンク数.

        """
        indexer = Indexer(input_dirs=input_dirs)
        chunks = indexer.load_and_chunk()

        if not chunks:
            return 0

        if update_only:
            # 差分更新のときは, 更新対象のファイルの古いチャンクを取り除き, 重複を避ける
            sources = sorted(
                {
                    str(chunk["metadata"]["source"])
                    for chunk in chunks
                    if chunk["metadata"].get("source")
                }
            )
            self.vector_store.delete_by_sources(sources)
        else:
            # 新規作成 (新規インデックス化) のときは既存のベクトルストア内容をクリア
            self.vector_store.clear()

        added_ids = self.vector_store.add_chunks(chunks)
        return len(added_ids)

    def get_context(self, question: str, k: int = 5) -> str:
        """質問に関連するコード情報を整形済みコンテキスト文字列として取得します.

        Args:
            question (str): ユーザーの質問文字列.
            k (int, optional): 参照する取得チャンク数. Defaults to 5.

        Returns:
            str: 整形されたコンテキスト文字列.

        """
        docs = self.vector_store.as_retriever(k=k).invoke(question)
        return self._format_docs(docs)

    def clear(self) -> None:
        """Vector DB を削除 (初期化) します."""
        self.vector_store.clear()

    def get_status(self) -> str:
        """インデックス（VectorStore）の現在のステータス情報を取得します.

        Returns:
            str: ステータス概要テキスト.

        """
        # VectorStore から件数を取得 (VectorStore 側に count() がある前提)
        chunk_count = self.vector_store.count()
        db_path = Path(self.output_dir).resolve()

        return f"データベースパス: {db_path}\n総インデックスチャンク数: {chunk_count}"

    def _format_docs(self, docs: list[Document]) -> str:
        """取得したドキュメント群をプロンプト埋め込み用の単一文字列に整形します.

        Args:
            docs: 整形対象のDocumentオブジェクトのリスト.

        Returns:
           各ドキュメントのソースパスと内容を結合したコンテキスト文字列.

        """
        formatted = []
        for doc in docs:
            source = doc.metadata.get("source", "Unknown")
            formatted.append(f"--- File: {source} ---\n{doc.page_content}")
        return "\n\n".join(formatted)
