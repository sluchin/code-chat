"""コードリポジトリのインデックス作成およびチャンク分割モジュール."""

from pathlib import Path
from typing import Any

from langchain_community.document_loaders.generic import GenericLoader
from langchain_community.document_loaders.parsers import LanguageParser
from langchain_text_splitters import Language, RecursiveCharacterTextSplitter


# pylint: disable=too-few-public-methods
class CodeIndexer:
    """リポジトリからのソースコードファイルの読み出しとチャンク分割を処理します."""

    def __init__(
        self,
        repo_path: str | None = None,
        suffixes: list[str] | None = None,
        chunk_size: int = 1000,
        chunk_overlap: int = 100,
    ) -> None:
        self.repo_path = str(repo_path)
        # 対象とする拡張子のデフォルト設定
        self.suffixes = suffixes or [".py", ".cpp", ".hpp", ".c", ".h", ".ts", ".js"]
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def load_and_chunk(self) -> list[dict[str, Any]]:
        """コードファイルを読み込み. チャンクに分割します.

        Returns:
            コンテンツとメタデータを含む辞書のチャンクリスト.
        """
        path = Path(self.repo_path)
        if not path.exists():
            raise FileNotFoundError(f"リポジトリのパスが存在しません: {path}")

        # リポジトリからファイルをロード (LanguageParser で構文情報を保持)
        loader = GenericLoader.from_filesystem(
            path=str(self.repo_path),
            glob="**/*",
            suffixes=self.suffixes,
            parser=LanguageParser(),
        )
        documents = loader.load()

        if not documents:
            return []

        # 言語に応じた TextSplitter でコード構造を意識して分割
        # 例として Python を指定 (必要に応じてファイル拡張子で動的切替も可能)
        splitter = RecursiveCharacterTextSplitter.from_language(
            language=Language.PYTHON,
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
        split_docs = splitter.split_documents(documents)

        # 戻り値の型 (list[dict[str, Any]]) にあわせて構造化
        chunks: list[dict[str, Any]] = []
        for doc in split_docs:
            chunks.append(
                {
                    "page_content": doc.page_content,
                    "metadata": doc.metadata,
                }
            )

        return chunks
