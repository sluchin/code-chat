"""コードRAG操作のための高レベルサービスインターフェース."""

from collections.abc import Generator

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_google_genai import ChatGoogleGenerativeAI

from code_chat_rag.code_indexer import CodeIndexer
from code_chat_rag.vector_store import VectorStore


class CodeRagService:
    """インデックス作成, 検索, コードクエリへの回答を調整するサービスレイヤー."""

    def __init__(
        self,
        repo_path: str | None = None,
        persist_directory: str = "./.chroma_db",
        model_name: str = "gemini-flash-latest",
    ) -> None:
        self.repo_path = str(repo_path)
        self.vector_store = VectorStore(persist_directory=persist_directory)
        self.llm = ChatGoogleGenerativeAI(model=model_name, temperature=0.0)

    def index_repository(self, repo_path: str) -> int:
        """コードリポジトリを読み込み, チャンク化してVectorStoreに保存します.

        Args:
            repo_path: コードリポジトリディレクトリへのパス.

        Returns:
            インデックスされたチャンク数.
        """
        indexer = CodeIndexer(repo_path=repo_path)
        chunks = indexer.load_and_chunk()

        if not chunks:
            return 0

        added_ids = self.vector_store.add_chunks(chunks)
        return len(added_ids)

    def _build_chain(self, k: int = 5):
        """LangChain Expression Language (LCEL) を使用してRAGパイプラインを構築します."""
        retriever = self.vector_store.as_retriever(k=k)

        # ドキュメント群を1つのコンテキスト文字列に整形するヘルパー.
        def format_docs(docs):
            formatted = []
            for doc in docs:
                source = doc.metadata.get("source", "Unknown")
                formatted.append(f"--- File: {source} ---\n{doc.page_content}")
            return "\n\n".join(formatted)

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
                "context": retriever | format_docs,
                "question": RunnablePassthrough(),
            }
            | prompt
            | self.llm
            | StrOutputParser()
        )
        return chain

    def ask(self, question: str, k: int = 5) -> str:
        """インデックスされたコードベースを使用してコードに関する質問に回答します.

        Args:
            question: ユーザーのクエリ文字列.
            k: 参照する取得チャンク数.

        Returns:
            生成された回答テキスト.
        """
        chain = self._build_chain(k=k)
        return chain.invoke(question)

    def ask_stream(self, question: str, k: int = 5) -> Generator[str, None, None]:
        """レスポンシブなCLIインタラクションのために回答トークンをストリーミングします.

        Args:
            question: ユーザーのクエリ文字列.
            k: 参照する取得チャンク数.

        Yields:
            LLMによって生成されたトークンチャンク.
        """
        chain = self._build_chain(k=k)
        yield from chain.stream(question)
