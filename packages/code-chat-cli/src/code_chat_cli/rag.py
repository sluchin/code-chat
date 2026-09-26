"""CLI から呼び出されるインデックス作成および質問応答のハンドラーモジュール."""

from pathlib import Path  # pylint: disable=unused-import

from code_chat_rag.indexer import Indexer
from code_chat_rag.rag_service import RagService

from code_chat_cli.logger import get_logger

logger = get_logger(__name__)


def handle_rag_create(
    input_dirs: list[str],
    output_dir: str = "./.chroma_db",
    dryrun: bool = False,
) -> None:
    """指定されたリポジトリのインデックスを作成し, 結果を標準出力に出力する.

    Args:
        input_dirs (list[str]): インデックス作成対象のリポジトリのパス.
        output_dir (str): ベクトルストアの永続化先ディレクトリ.
        dryrun (bool): True の場合はインデックス作成を実行せず, 対象ファイル一覧を表示する.

    """
    try:
        logger.debug("RagService の初期化を開始します")
        service = RagService(output_dir=output_dir)

        if dryrun:
            print("[DRY-RUN] インデックスの更新対象ファイルを計算します...")
            _handle_dryrun(input_dirs=input_dirs)
            return

        logger.info("新規作成モードでインデックス処理を開始します")
        count = service.index_repository(input_dirs)

        # フルパス（絶対パス）を取得
        full_db_path = Path(output_dir).resolve()
        print(f"インデックス作成完了: {count} チャンク追加 (Database: {full_db_path})")
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("handle_index 実行中にエラーが発生しました")


def handle_rag_update(
    input_dirs: list[str],
    output_dir: str = "./.chroma_db",
    dryrun: bool = False,
) -> None:
    """指定されたリポジトリのインデックスを作成し, 結果を標準出力に出力する.

    Args:
        input_dirs (list[str]): インデックス作成対象のリポジトリのパス.
        output_dir (str): ベクトルストアの永続化先ディレクトリ.
        dryrun (bool): True の場合はインデックス作成を実行せず, 対象ファイル一覧を表示する.

    """
    try:
        logger.debug("RagService の初期化を開始します")
        service = RagService(output_dir=output_dir)

        if dryrun:
            print("[DRY-RUN] インデックスの更新対象ファイルを計算します...")
            _handle_dryrun(input_dirs=input_dirs)
            return

        logger.info("差分更新モードでインデックス処理を開始します")
        count = service.index_repository(input_dirs, update_only=True)

        # フルパス（絶対パス）を取得
        full_db_path = Path(output_dir).resolve()
        print(f"インデックス作成完了: {count} チャンク追加 (Database: {full_db_path})")
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("handle_index 実行中にエラーが発生しました")


def handle_rag_rm(
    output_dir: str = "./.chroma_db",
) -> None:
    """指定されたベクトルストアのインデックスを削除（初期化）します.

    Args:
        output_dir (str): ベクトルストアの永続化先ディレクトリ.

    """
    try:
        logger.info("インデックス初期化を開始します")
        service = RagService(output_dir=output_dir)
        service.clear()
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("handle_index 実行中にエラーが発生しました")


def handle_rag_status(input_dirs: list[str], output_dir: str) -> None:
    """RAG インデックスのステータスを確認し, 結果を表示します.

    Args:
        input_dirs (list[str]): インデックス作成対象のリポジトリのパス.
        output_dir (str): ベクトルストアの永続化先ディレクトリ.

    """
    logger.info("RAG インデックスの状態を確認します")
    service = RagService(input_dirs=input_dirs, output_dir=output_dir)
    status_info = service.get_status()
    print(f"--- [RAG Index Status] ---\n{status_info}")


def handle_rag(question: str) -> None:
    """質問に対して RagService を呼び出し, 回答をリアルタイムでストリーミング出力する.

    Args:
        question (str): ユーザーから入力された質問文.

    """
    service = RagService(output_dir="./.chroma_db")

    # CLI向けにストリーミング出力
    for token in service.query_stream(question):
        print(token, end="", flush=True)
    print()


def _handle_dryrun(input_dirs: list[str]) -> None:
    """インデックス作成対象のファイルを計算し, 一覧を表示します.

    Args:
        input_dirs (list[str]): インデックス作成対象のリポジトリのパス.

    """
    all_target_files: list[str] = []
    indexer = Indexer(input_dirs=input_dirs)
    target_files = indexer.get_target_files()
    all_target_files.extend(target_files)
    for file_path in target_files:
        print(file_path)
    print(f"対象ファイル数: {len(all_target_files)}")
