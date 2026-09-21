"""コードRAG操作のための高レベルサービスインターフェース."""

from collections.abc import Generator
from pathlib import Path

from code_chat_cli.logger import get_logger
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnablePassthrough
from langchain_google_genai import ChatGoogleGenerativeAI

from code_chat_rag.code_indexer import CodeIndexer
from code_chat_rag.vector_store import VectorStore

logger = get_logger(__name__)


class CodeRagService:
    """インデックス作成, 検索, コードクエリへの回答を調整するサービスレイヤー."""

    def __init__(
        self,
        input_dirs: list[str] | None = None,
        output_dir: str = "./chroma_db",
        model_name: str = "gemini-3.5-flash",
    ) -> None:
        """CodeRagServiceのインスタンスを初期化します.

        Args:
            index_dirs: 対象のコードリポジトリへのパス.
            output_dir: ベクトルストアの永続化先ディレクトリ.
            model_name: 使用するLLMのモデル名.
        """
        self.input_dirs = input_dirs
        self.output_dir = output_dir
        self.vector_store = VectorStore(output_dir=output_dir)
        doc_count = self.vector_store.count()
        logger.info("RAG Vector DB: %s", output_dir)
        logger.info("RAG DB 登録ドキュメント数: %d 件", doc_count)
        self.llm = ChatGoogleGenerativeAI(model=model_name, temperature=0.0)

    def index_repository(self, input_dirs: list[str], update_only: bool = False) -> int:
        """コードリポジトリを読み込み, チャンク化してVectorStoreに保存します.

        Args:
            input_dirs: コードリポジトリディレクトリへのパス.
            update_only: True の場合は既存データを消さずに差分追加/更新し, False の場合は初期化して全件再作成します.

        Returns:
            インデックスされたチャンク数.
        """
        indexer = CodeIndexer(input_dirs=input_dirs)
        chunks = indexer.load_and_chunk()

        if not chunks:
            return 0

        if not update_only:
            # 新規作成 (新規インデックス化) のときは既存のベクトルストア内容をクリア
            self.vector_store.clear()

        added_ids = self.vector_store.add_chunks(chunks)
        return len(added_ids)

    def get_context(self, question: str, k: int = 5) -> str:
        """質問に関連するコード情報を整形済みコンテキスト文字列として取得します."""
        docs = self.vector_store.as_retriever(k=k).invoke(question)
        return self._format_docs(docs)

    def clear(self):
        """Vector DB 削除"""
        self.vector_store.clear()

    def query(self, question: str, k: int = 5) -> str:
        """インデックスされたコードベースを使用してコードに関する質問に回答します.

        Args:
            question: ユーザーのクエリ文字列.
            k: 参照する取得チャンク数.

        Returns:
            生成された回答テキスト.
        """
        chain = self._build_chain(k=k)
        return chain.invoke(question)

    def query_stream(self, question: str, k: int = 5) -> Generator[str, None, None]:
        """レスポンシブなCLIインタラクションのために回答トークンをストリーミングします.

        Args:
            question: ユーザーのクエリ文字列.
            k: 参照する取得チャンク数.

        Yields:
            LLMによって生成されたトークンチャンク.
        """
        chain = self._build_chain(k=k)
        yield from chain.stream(question)

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

    def _build_chain(self, k: int = 5) -> Runnable:
        """LangChain Expression Language (LCEL) を使用してRAGパイプラインを構築します.

        Args:
            k: 検索時に取得するチャンク数.

        Returns:
            質問文字列を受け取り, 回答文字列を出力する実行可能なLCELチェーン.
        """
        retriever = self.vector_store.as_retriever(k=k)

        prompt = ChatPromptTemplate.from_template(
            "あなたはコードベースの解釈と解説を行うエキスパートです.\n"
            "以下のコンテキスト（コード情報）のみを参照して, ユーザーの質問に正確に答えてください.\n"
            "コンテキストから分からない場合は「指定されたコード範囲からは回答できません」と答えてください.\n\n"
            "【コンテキスト】\n"
            "{context}\n\n"
            "【質問】\n"
            "{question}"
        )

        chain = (
            {
                "context": retriever | self._format_docs,
                "question": RunnablePassthrough(),
            }
            | prompt
            | self.llm
            | StrOutputParser()
        )
        return chain
