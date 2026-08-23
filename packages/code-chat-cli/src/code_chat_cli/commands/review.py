"""コードレビューサブコマンドの処理."""

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from code_chat_cli.constants import TEXT_EXTENSIONS
from code_chat_cli.prompts import REVIEW_PROMPT_TEMPLATE


def _collect_directory_files(target_dir: Path) -> str:
    """指定ディレクトリ配下のテキストファイルを走査・収集します.

    指定されたディレクトリ配下を再帰的に検索し、指定の拡張子を持つ
    テキストファイルの内容を単一の文字列に結合して返します.
    特定の大規模・生成ディレクトリ（.git, node_modules等）は除外されます.

    Args:
        target_dir (Path): 走査対象のディレクトリパス.

    Returns:
        str: 収集されたファイル群の内容を結合したテキスト.
    """
    ignored_dirs = {".git", "__pycache__", ".venv", ".chroma_db", "node_modules"}
    collected_files: list[str] = []

    for root, dirs, files in os.walk(target_dir):
        dirs[:] = [d for d in dirs if d not in ignored_dirs]
        for file in files:
            file_p = Path(root) / file
            if file_p.suffix.lower() not in TEXT_EXTENSIONS:
                continue
            try:
                content = file_p.read_text(encoding="utf-8")
                collected_files.append(f"=== File: {file_p} ===\n{content}")
            except (OSError, UnicodeDecodeError) as e:
                print(
                    f"スキップ (読み込み失敗): {file_p} - {e}",
                    file=sys.stderr,
                )

    return "\n\n".join(collected_files)


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
        path = Path(file_path)
        if not path.exists():
            print(f"エラー: 指定されたパスが存在しません: {file_path}", file=sys.stderr)
            return

        if path.is_dir():
            target_code = _collect_directory_files(path)
        else:
            try:
                content = path.read_text(encoding="utf-8")
                target_code = f"=== File: {path} ===\n{content}"
            except (OSError, UnicodeDecodeError) as e:
                print(f"エラー: ファイルの読み込みに失敗しました: {e}", file=sys.stderr)
                return
    else:
        target_code = _get_git_diff(staged)

    if not target_code:
        print("レビュー対象のコードまたは変更点が見つかりませんでした.")
        return

    prompt = REVIEW_PROMPT_TEMPLATE.format(code=target_code)

    print("コードレビューを実行中...\n")
    response = client.models.generate_content_stream(
        model=model_name,
        contents=prompt,
    )
    for chunk in response:
        print(chunk.text, end="", flush=True)
    print()
