"""コミットメッセージ自動生成サブコマンドの処理."""

import subprocess
from typing import Any

from code_chat_cli.api import send_message_stream_with_retry
from code_chat_cli.git_utils import get_git_diff
from code_chat_cli.logger import get_logger
from code_chat_cli.prompts import Prompts

logger = get_logger(__name__)


def handle_commit_generation(client: Any, model_name: str) -> None:
    """Git の diff（差分）を取得し, Gemini API を用いてコミットメッセージを自動生成します.

    ステージング済み差分 (`git diff --staged`) および未ステージング差分 (`git diff`) を
    読み取り, 変更内容が存在する場合に Conventional Commits 形式に沿った
    英語のコミットメッセージを生成して標準出力に表示します.

    Args:
        client (Any): Gemini API クライアントインスタンス.
        model_name (str): 使用する Gemini モデル名.

    Raises:
        subprocess.CalledProcessError: Git コマンドの実行に失敗した場合.
        APIError: Gemini API 呼び出し時に通信エラー等が発生した場合.
        ClientError: Gemini API 呼び出し時にクライアントエラーが発生した場合.
        ServerError: Gemini API 呼び出し時にサーバーエラーが発生した場合.
        Exception: その他の予期せぬエラーが発生した場合.

    """
    try:
        diff_text = get_git_diff()

        if not diff_text:
            print(
                "変更（git diff）が検出されませんでした.ファイルを修正するか `git add` してください."
            )
            return

        prompt = Prompts.COMMIT_PROMPT_TEMPLATE.format(diff=diff_text)

        # 失敗した場合の APIError は, 呼び出し元 (chat) が概要とヒントを 1 回だけ出力する
        response_stream = send_message_stream_with_retry(
            chat=client.chats.create(model=model_name), prompt=prompt
        )

        for chunk in response_stream:
            # 使用状況だけを含む最後のチャンクなど, テキストが空のものは出力しない
            if chunk.text:
                print(chunk.text, end="", flush=True)
        print()

    except subprocess.CalledProcessError as e:
        logger.error("Git コマンドの実行に失敗しました: %s", e)
        raise
