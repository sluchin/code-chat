"""コードレビューサブコマンドの処理."""

import logging
import subprocess
import sys
from typing import Any

from code_chat_cli.args import read_path_content
from code_chat_cli.prompts import REVIEW_PROMPT_TEMPLATE

logger = logging.getLogger(__name__)


def handle_code_review(
    client: Any,
    model_name: str,
    staged: bool = False,
    file_path: str | None = None,
) -> None:
    """コード差分または指定ファイルを解析し, LLM によるコードレビュー結果を表示する.

    Args:
        client (Any): Gemini API クライアントインスタンス.
        model_name (str): 使用する Gemini モデル名.
        staged (bool, optional): True の場合, git diff の --cached
            (ステージング済み) 差分を対象にする. Defaults to False.
        file_path (str | None, optional): レビュー対象のファイルまたは
            ディレクトリのパス. 指定された場合は git diff ではなく
            ファイル内容全体をレビューする. Defaults to None.
    """
    target_code: str | None = ""

    if file_path:
        logger.info(
            "-f オプションが指定されたため、ファイル/ディレクトリをコンテキストとして読み込みます: %s",
            file_path,
        )
        target_code = read_path_content(file_path)
    else:
        logger.info("git diff から変更差分を取得してレビューを実施します.")
        target_code = _get_git_diff(staged)

    if not target_code:
        print("レビュー対象のコードまたは変更点が見つかりませんでした.")
        return

    logger.info("コードレビュー対象のコンテキストサイズ: %d 文字", len(target_code))

    prompt = REVIEW_PROMPT_TEMPLATE.format(code=target_code)

    print("コードレビューを実行中...\n")

    try:
        response = client.models.generate_content_stream(
            model=model_name,
            contents=prompt,
        )
        for chunk in response:
            print(chunk.text, end="", flush=True)
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.exception("コードレビュー実行中にエラーが発生しました")
        print(f"\nエラーが発生しました: {e}", file=sys.stderr)

    print()


def _get_git_diff(staged: bool) -> str | None:
    """git diff から変更差分を取得します.

    Args:
        staged (bool): True の場合 `--cached` (ステージング済み) 差分を取得する.

    Returns:
        str | None: 取得した差分文字列. 実行失敗時または git コマンドが
            存在しない場合は None を返す.
    """
    cmd = ["git", "diff", "--cached"] if staged else ["git", "diff"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            print(
                f"エラー: git diff の実行に失敗しました:\n{result.stderr}",
                file=sys.stderr,
            )
            return None
        return result.stdout.strip()
    except FileNotFoundError:
        print("エラー: git コマンドが見つかりません.", file=sys.stderr)
        return None
