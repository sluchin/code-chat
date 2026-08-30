"""コミットメッセージ自動生成サブコマンドの処理."""

import logging
import subprocess
import sys
from typing import Any

from google.genai.errors import APIError, ClientError, ServerError

from code_chat_cli.api import send_message_stream_with_retry
from code_chat_cli.git_utils import get_git_diff
from code_chat_cli.logger import get_logger
from code_chat_cli.prompts import COMMIT_PROMPT_TEMPLATE_JA, COMMIT_PROMPT_TEMPLATE_EN

logger = get_logger(__name__)


def handle_commit_generation(
    client: Any, model_name: str, lang: str = "en"
) -> None:
    """Git の diff（差分）を取得し, Gemini API を用いてコミットメッセージを自動生成します.

    `git diff --staged`（ステージング済み差分）および `git diff`（未ステージング差分）を
    読み取り, 変更内容が存在する場合に指定された言語で Conventional Commits 形式に沿った
    適切なコミットメッセージを生成して標準出力に表示します.

    Args:
        client (Any): Gemini API クライアントインスタンス.
        model_name (str): 使用する Gemini モデル名.
        lang (str, optional): コミットメッセージの出力言語（例: "ja", "en"）. デフォルトは "en".

    Raises:
        subprocess.CalledProcessError: Git コマンドの実行に失敗した場合.
        APIError: Gemini API 呼び出し時に通信エラーや 503 等が発生した場合.
        Exception: その他の予期せぬエラーが発生した場合.
    """
    try:
        diff_text = get_git_diff()

        if not diff_text:
            print(
                "変更（git diff）が検出されませんでした.ファイルを修正するか `git add` してください."
            )
            return

        # 言語に応じたテンプレートの選択（標準を日本語に設定）
        template = (
            COMMIT_PROMPT_TEMPLATE_JA if lang == "ja" else COMMIT_PROMPT_TEMPLATE_EN
        )
        prompt = template.format(diff=diff_text)

        try:
            response_stream = send_message_stream_with_retry(
                chat=client.chats.create(model=model_name), prompt=prompt
            )

            for chunk in response_stream:
                print(chunk.text, end="", flush=True)
            print()

        except Exception as e:  # pylint: disable=broad-exception-caught
            error_detail = (
                str(e) if logger.isEnabledFor(logging.DEBUG) else type(e).__name__
            )
            logger.error(
                "コミットメッセージの生成中にエラーが発生しました: %s",
                error_detail,
            )
            raise

    except subprocess.CalledProcessError as e:
        logger.error("Git コマンドの実行に失敗しました: %s", e)
        raise
    except (APIError, ServerError, ClientError) as e:
        error_detail = (
            str(e) if logger.isEnabledFor(logging.DEBUG) else type(e).__name__
        )
        logger.error("Gemini API でエラーが発生しました: %s", error_detail)
        raise
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("予期せぬエラーが発生しました: %s", e)
        raise
