"""コードリポジトリのインデックス作成およびチャンク分割モジュール.

指定されたリポジトリ配下のソースコードファイルを読み込み,
各プログラミング言語の構文に応じた適切なチャンク分割処理を行います.
"""

from pathlib import Path
from typing import Any

from langchain_community.document_loaders.generic import GenericLoader
from langchain_community.document_loaders.parsers import LanguageParser
from langchain_text_splitters import Language, RecursiveCharacterTextSplitter

# 拡張子と LangChain Language 列挙型のマッピング
EXTENSION_TO_LANGUAGE: dict[str, Language] = {
    ".py": Language.PYTHON,
    ".pyw": Language.PYTHON,
    ".js": Language.JS,
    ".mjs": Language.JS,
    ".cjs": Language.JS,
    ".jsx": Language.JS,
    ".ts": Language.TS,
    ".tsx": Language.TS,
    ".c": Language.CPP,
    ".cc": Language.CPP,
    ".cpp": Language.CPP,
    ".cxx": Language.CPP,
    ".h": Language.CPP,
    ".hpp": Language.CPP,
}


# pylint: disable=too-few-public-methods
class CodeIndexer:
    """リポジトリからのソースコードファイルの読み出しとチャンク分割を処理します.

    Attributes:
        repo_path (str): 走査対象のリポジトリのルートパス.
        suffixes (list[str]): 読み込み対象とするファイルの拡張子リスト.
        chunk_size (int): チャンクの最大文字数.
        chunk_overlap (int): チャンク間のオーバーラップ文字数.
    """

    def __init__(
        self,
        repo_path: str | None = None,
        suffixes: list[str] | None = None,
        chunk_size: int = 1000,
        chunk_overlap: int = 100,
    ) -> None:
        """CodeIndexer を初期化します.

        Args:
            repo_path (str | None, optional): 走査対象のリポジトリパス. Defaults to None.
            suffixes (list[str] | None, optional): 対象拡張子のリスト. 指定がない場合は
                [".py", ".cpp", ".hpp", ".c", ".h", ".ts", ".js"] が使用されます.
                Defaults to None.
            chunk_size (int, optional): チャンクの最大サイズ. Defaults to 1000.
            chunk_overlap (int, optional): チャンク間のオーバーラップサイズ. Defaults to 100.
        """
        self.repo_path = str(repo_path)
        # 対象とする拡張子のデフォルト設定
        self.suffixes = suffixes or [".py", ".cpp", ".hpp", ".c", ".h", ".ts", ".js"]
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def load_and_chunk(self) -> list[dict[str, Any]]:
        """コードファイルを読み込み, 言語に応じた適正なチャンクに分割します.

        ドキュメントのファイル拡張子を判定し, 言語ごとの構文（関数やクラスの区切り等）を
        考慮したスプリッターを動的に適用してチャンクを作成します.

        Returns:
            list[dict[str, Any]]: チャンク化されたテキストとそのメタデータを含む辞書のリスト.
                各要素は {"page_content": str, "metadata": dict} の形式を持ちます.

        Raises:
            FileNotFoundError: 指定された `repo_path` が存在しない場合に発生します.
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

        # ファイル単位で適切なスプリッターを選択して分割
        split_docs = []
        for doc in documents:
            source_path = doc.metadata.get("source", "")
            splitter = self._get_splitter_for_path(source_path)
            split_docs.extend(splitter.split_documents([doc]))

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

    def _get_splitter_for_path(self, file_path: str) -> RecursiveCharacterTextSplitter:
        """ファイルパスの拡張子に応じた RecursiveCharacterTextSplitter を生成します.

        マッピングテーブルに対応する言語定義が存在する場合はその言語用のスプリッターを返し,
        存在しない場合は汎用の文字ベーススプリッターにフォールバックします.

        Args:
            file_path (str): 判定対象のファイルパス.

        Returns:
            RecursiveCharacterTextSplitter: 対象言語用に設定されたテキストスプリッター.
        """
        ext = Path(file_path).suffix.lower()
        language = EXTENSION_TO_LANGUAGE.get(ext)

        if language:
            return RecursiveCharacterTextSplitter.from_language(
                language=language,
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap,
            )

        # マッピングにない拡張子の場合は汎用スプリッターにフォールバック
        return RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )
