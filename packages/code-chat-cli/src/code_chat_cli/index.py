"""CLI から呼び出されるインデックス作成および質問応答のハンドラーモジュール."""

from pathlib import Path  # pylint: disable=unused-import

from code_chat_rag.code_rag_service import CodeRagService

from code_chat_cli.logger import get_logger

logger = get_logger(__name__)


def handle_index(
    input_dirs: list[str],
    output_dir: str = "./.chroma_db",
    update_only: bool = False,
) -> None:
    """指定されたリポジトリのインデックスを作成し, 結果を標準出力に出力する.

    Args:
        input_dirs (list[str]): インデックス作成対象のリポジトリのパス.
        output_dir: ベクトルストアの永続化先ディレクトリ.
        update_only (bool): True の場合は差分更新のみを実行する.
    """
    try:
        logger.debug("CodeRagService の初期化を開始します")
        service = CodeRagService(output_dir=output_dir)

        if update_only:
            logger.info("差分更新モードでインデックス処理を開始します")
            # CodeRagService 側に update_repository
            # (または update_only フラグ付きの index_repository) が存在することを想定
            count = service.index_repository(input_dirs, update_only=update_only)

            # フルパス（絶対パス）を取得
            full_db_path = Path(output_dir).resolve()
            print(
                f"インデックス更新完了: {count} チャンク更新/追加 (Database: {full_db_path})"
            )
        else:
            logger.info("新規作成モードでインデックス処理を開始します")
            count = service.index_repository(input_dirs)

            # フルパス（絶対パス）を取得
            full_db_path = Path(output_dir).resolve()
            print(
                f"インデックス作成完了: {count} チャンク追加 (Database: {full_db_path})"
            )

        # フルパス（絶対パス）を取得
        full_db_path = Path(output_dir).resolve()
        print(f"Index completed: {count} chunks added. (Database: {full_db_path})")
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("handle_index 実行中にエラーが発生しました")


def clear_index(
    output_dir: str = "./.chroma_db",
) -> None:
    """指定されたリポジトリのインデックスを作成し, 結果を標準出力に出力する.

    Args:
        output_dir: ベクトルストアの永続化先ディレクトリ.
    """
    try:
        logger.info("インデックス初期化を開始します")
        service = CodeRagService(output_dir=output_dir)
        service.clear()
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("handle_index 実行中にエラーが発生しました")


def handle_rag(question: str) -> None:
    """質問に対して CodeRagService を呼び出し, 回答をリアルタイムでストリーミング出力する.

    Args:
        question (str): ユーザーから入力された質問文.
    """
    service = CodeRagService(output_dir="./.chroma_db")

    # CLI向けにストリーミング出力
    for token in service.query_stream(question):
        print(token, end="", flush=True)
    print()
