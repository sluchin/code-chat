"""コードリポジトリのインデックス作成およびチャンク分割モジュール.

指定されたリポジトリ配下のソースコードファイルを読み込み,
各プログラミング言語の構文に応じた適切なチャンク分割処理を行います.
"""

from pathlib import Path
from typing import Any

from code_chat_cli.logger import get_logger
from langchain_community.document_loaders import TextLoader
from langchain_community.document_loaders.generic import GenericLoader
from langchain_community.document_loaders.parsers import LanguageParser
from langchain_text_splitters import Language, RecursiveCharacterTextSplitter

# プロジェクト共通の定数や拡張子定義
EXCLUDE_DIRS = {".git", ".venv", ".env", "__pycache__", "node_modules", "build", "dist"}
TARGET_EXTENSIONS = {".py", ".cpp", ".hpp", ".c", ".h", ".ts", ".js"}

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

logger = get_logger(__name__)


# pylint: disable=too-few-public-methods
class CodeIndexer:
    """リポジトリからのソースコードファイルの読み出しとチャンク分割を処理します.

    Attributes:
        input_dirs (list[str]): 走査対象のリポジトリのルートパス.
        suffixes (list[str]): 読み込み対象とするファイルの拡張子リスト.
        chunk_size (int): チャンクの最大文字数.
        chunk_overlap (int): チャンク間のオーバーラップ文字数.
    """

    def __init__(
        self,
        input_dirs: list[str] | None = None,
        suffixes: list[str] | None = None,
        chunk_size: int = 1000,
        chunk_overlap: int = 100,
    ) -> None:
        """CodeIndexer を初期化します.

        Args:
            input_dirs (list[str] | None, optional): 走査対象のリポジトリパス. Defaults to None.
            suffixes (list[str] | None, optional): 対象拡張子のリスト. 指定がない場合は
                [".py", ".cpp", ".hpp", ".c", ".h", ".ts", ".js"] が使用されます.
                Defaults to None.
            chunk_size (int, optional): チャンクの最大サイズ. Defaults to 1000.
            chunk_overlap (int, optional): チャンク間のオーバーラップサイズ. Defaults to 100.
        """
        self.input_dirs = input_dirs
        # 対象とする拡張子のデフォルト設定
        self.suffixes = suffixes or TARGET_EXTENSIONS
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
            FileNotFoundError: 指定された `input_dirs` が存在しない場合に発生します.
        """
        # 有効な Path オブジェクトのリストを取得
        valid_dirs = self._get_valid_input_dirs()

        # 有効なディレクトリが1つも存在しない場合は例外をスロー
        if not valid_dirs:
            raise FileNotFoundError(
                f"指定されたインデックス対象ディレクトリが存在しません: {self.input_dirs}"
            )

        # 有効な Path リストで更新
        self.input_dirs = valid_dirs

        # 空のリストで初期化
        documents: list[str] = []

        # 対象ファイルの抽出
        target_files = self.get_target_files()
        for file in target_files:
            # LanguageParser (GenericLoader / LanguageParser 単体) での構文解析を試みる
            file_path = Path(file)
            try:
                # 単一ファイルに対する LanguageParser のロード
                loader = GenericLoader.from_filesystem(
                    path=str(file_path.parent),
                    glob=file_path.name,
                    parser=LanguageParser(),
                )
                file_docs = loader.load()
                documents.extend(file_docs)
            except Exception:  # noqa: BLE001 # pylint: disable=broad-exception-caught
                # tree-sitter 未インストールや構文解析失敗時
                # フォールバック: TextLoader でプレーンテキストとして読み込む
                try:
                    fallback_loader = TextLoader(
                        str(file_path),
                        encoding="utf-8",
                        autodetect_encoding=True,
                    )
                    documents.extend(fallback_loader.load())
                except Exception as e:  # noqa: BLE001 # pylint: disable=broad-exception-caught
                    logger.warning(
                        "ファイル '%s' の読み込みに失敗しました: %s", file_path, e
                    )
                    continue

        if not documents:
            return []

        # ファイル単位で適切なスプリッターを選択して分割
        split_docs = []
        for doc in documents:
            # doc が Document オブジェクトであることを保証/明示
            if hasattr(doc, "metadata") and isinstance(doc.metadata, dict):
                source_path = str(doc.metadata.get("source", ""))
            else:
                source_path = ""
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

    def get_target_files(self) -> list[str]:
        """指定されたリポジトリパスからインデックス対象となるファイルのリストを取得します."""
        target_files: list[str] = []
        seen_files: set[Path] = set()

        input_dirs = self.input_dirs or []
        for input_dir in input_dirs:
            path = Path(input_dir)
            if not path.exists():
                continue

            for file_path in path.rglob("*"):
                if not file_path.is_file():
                    continue

                if file_path.suffix.lower() not in TARGET_EXTENSIONS:
                    continue

                # 親ディレクトリ配下に除外対象または隠しフォルダが含まれている場合はスキップ
                if any(
                    part in EXCLUDE_DIRS
                    or (part.startswith(".") and part not in (".", ".."))
                    for part in file_path.parts[:-1]
                ):
                    continue

                # 重複登録を避けるためのチェック (パスを正規化して比較)
                resolved_path = file_path.resolve()
                if resolved_path not in seen_files:
                    seen_files.add(resolved_path)
                    target_files.append(str(file_path))

        return sorted(target_files)

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

    def _get_valid_input_dirs(self) -> list[str]:
        """input_dirs から実際に存在するディレクトリパスのリストを取得します.

        Returns:
            list[str]: 存在するディレクトリの Path オブジェクトリスト.
        """
        valid_dirs: list[str] = []

        input_dirs = self.input_dirs or []
        for dir_path in input_dirs:
            if not dir_path:
                continue

            path = Path(dir_path)
            if path.exists() and path.is_dir():
                valid_dirs.append(dir_path)
            else:
                logger.warning(
                    "インデックス対象のディレクトリが存在しないか、ディレクトリではありません: '%s'",
                    dir_path,
                )

        return valid_dirs
