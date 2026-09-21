"""ファイル操作およびパス参照に関するユーティリティ機能を提供するモジュール

このモジュールは, 指定されたパスからのコンテキストデータの読み込みや
ファイル・ディレクトリの存在確認などのファイルシステム操作を提供します
"""

import os
import sys
from pathlib import Path

from code_chat_cli.constants import EXCLUDE_DIRS, TEXT_EXTENSIONS
from code_chat_cli.logger import get_logger

logger = get_logger(__name__)


def read_path_content(target_path: str) -> str:
    """指定されたパス (単一ファイルまたはディレクトリ) からコンテンツを読み込む.

    ディレクトリが指定された場合は再帰的に探索し, 対象の拡張子を持つファイルの内容を
    除外ディレクトリを回避しながら結合して返します.

    Args:
        target_path: 読み込み対象のファイルまたはディレクトリのパス.

    Returns:
        読み込まれたファイル内容のテキスト. 該当ファイルが存在しない場合は空文字列.

    Raises:
        SystemExit: 指定されたパスが存在しない場合, またはファイルの読み込みに失敗した場合に
            ステータスコード 1 で終了します.
    """
    path = Path(target_path)

    if not path.exists():
        logger.error("パス '%s' が見つかりません.", target_path)
        sys.exit(1)

    if path.is_file():
        try:
            return f"=== File: {path} ===\n" + path.read_text(encoding="utf-8")
        except OSError:
            logger.exception("ファイル '%s' の読み込みに失敗しました", path)
            sys.exit(1)

    if path.is_dir():
        contents: list[str] = []
        loaded_files: list[Path] = []

        # os.walk を使うことで除外ディレクトリ配下の走査を即座にスキップ可能
        for root, dirs, files in os.walk(path):
            # EXCLUDE_DIRS に含まれるディレクトリ配下を走査対象から除外
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

            for file in files:
                file_path = Path(root) / file
                if file_path.suffix.lower() in TEXT_EXTENSIONS:
                    try:
                        text = file_path.read_text(encoding="utf-8", errors="ignore")
                        contents.append(f"=== File: {file_path} ===\n{text}")
                        loaded_files.append(file_path)
                        logger.debug("読み込み完了: %s", file_path)
                    except OSError as e:
                        logger.warning(
                            "'%s' の読み込みをスキップしました: %s",
                            file_path,
                            e,
                        )

        if not contents:
            logger.warning(
                "ディレクトリ '%s' 内に対象ファイルが見つかりませんでした.",
                target_path,
            )
            return ""

        total_text = "\n\n".join(contents)
        logger.info(
            "ディレクトリ '%s' から %d 件のファイルをコンテキストとして読み込みました (合計: %d 文字).",
            target_path,
            len(loaded_files),
            len(total_text),
        )

        return total_text

    return ""
