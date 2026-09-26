"""Gemini API 通信およびリトライ処理を行うモジュール."""

import time
from collections.abc import Iterator
from typing import Any

from google.genai.errors import APIError, ClientError, ServerError

from code_chat_cli.gemini_error import (
    is_daily_quota_error,
    retry_delay_seconds,
    summarize_error,
)
from code_chat_cli.gemini_error_kind import GeminiErrorKind
from code_chat_cli.logger import get_logger

logger = get_logger(__name__)


def send_message_with_retry(
    chat: Any,
    prompt: str,
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
) -> Any:
    """Gemini API へのリクエストを送信し, 通信エラー発生時にリトライを行います.

    Args:
        chat (Any): Gemini Chat インスタンス.
        prompt (str): 送信するプロンプト文字列.
        max_retries (int, optional): 最大リトライ回数. デフォルトは 3.
        initial_delay (float, optional): 初回リトライ時の待ち時間（秒）. デフォルトは 1.0.
        backoff_factor (float, optional): 指数バックオフの倍率. デフォルトは 2.0.

    Returns:
        Any: Gemini API からのレスポンス.

    Raises:
        Exception: 最大リトライ回数を超えてエラーが発生した場合.
        AssertionError: 内部状態の不整合により例外オブジェクトが保持されなかった場合.

    """
    delay = initial_delay
    last_exception: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            return chat.send_message(prompt)

        except APIError as e:
            last_exception = e
            if attempt == max_retries or not _is_retryable_error(e):
                break

            api_retry_delay = retry_delay_seconds(e)
            if api_retry_delay is not None:
                sleep_time = api_retry_delay + 1.0
            else:
                sleep_time = delay
                delay *= backoff_factor

            logger.warning(
                "Gemini API で一時的なエラーが発生しました (%d/%d): %s. %.1f秒後に再試行します...",
                attempt,
                max_retries,
                summarize_error(e),
                sleep_time,
            )
            time.sleep(sleep_time)

    # ここに到達した時点で last_exception は必ず存在する
    assert last_exception is not None  # 型チェッカーへの明示
    raise last_exception


def send_message_stream_with_retry(
    chat: Any,
    prompt: str,
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
) -> Iterator[Any]:
    """Gemini API へのストリーミングリクエストを送信し, 通信エラー発生時にリトライを行います.

    イテレーション中の API エラー（503/429等）もキャッチして再試行します.
    途中でエラーが発生した場合は画面に通知し, リトライ時は最初からメッセージを送り直します.

    Args:
        chat (Any): Gemini Chat インスタンス.
        prompt (str): 送信するプロンプト文字列.
        max_retries (int, optional): 最大リトライ回数. デフォルトは 3.
        initial_delay (float, optional): 初回リトライ時の待ち時間（秒）. デフォルトは 1.0.
        backoff_factor (float, optional): 指数バックオフの倍率. デフォルトは 2.0.

    Yields:
        Any: Gemini API からのレスポンスチャンク.

    Raises:
        Exception: 最大リトライ回数を超えてエラーが発生した場合, または出力開始後に通信エラーが発生した場合.

    """
    delay = initial_delay

    for attempt in range(1, max_retries + 1):
        has_yielded_content = False

        try:
            response_stream = chat.send_message_stream(prompt)
            for chunk in response_stream:
                has_yielded_content = True  # チャンクをひとつでも送出したら True に変更
                yield chunk
            return  # 正常終了

        except APIError as e:
            # 既にユーザーに画面出力が開始されている途中で切れた場合は,
            # 出力の重複を防ぐためリトライせずにエラーを送出する
            if (
                has_yielded_content
                or attempt == max_retries
                or not _is_retryable_error(e)
            ):
                if has_yielded_content:
                    logger.error(
                        "ストリーミングの受信途中でエラーが発生しました (一部出力済みのため, リトライせずに中断します)"
                    )
                raise

            # API側から retryDelay の指定があれば優先, なければ指数バックオフ
            api_retry_delay = retry_delay_seconds(e)
            if api_retry_delay is not None:
                sleep_time = api_retry_delay + 1.0
            else:
                sleep_time = delay
                delay *= backoff_factor

            logger.warning(
                "Gemini API で一時的なエラーが発生しました (%d/%d): %s. %.1f秒後に再試行します...",
                attempt,
                max_retries,
                summarize_error(e),
                sleep_time,
            )
            time.sleep(sleep_time)


def _is_retryable_error(e: Exception) -> bool:
    """リトライ対象のエラー（503/429等）かどうかを判定します.

    Args:
        e (Exception): 検証対象の Gemini API 例外オブジェクト.

    Returns:
        bool: リトライ対象のエラーである場合は True, 400 Bad Request 等のリトライ不可エラーの場合は False.

    """
    # 1日あたりのクォータ超過 (RPD) は待機しても回復しないためリトライしない
    if is_daily_quota_error(e):
        return False

    # APIError, ServerError, ClientError すべてを対象
    if (
        isinstance(e, (APIError, ServerError, ClientError))
        and e.code in GeminiErrorKind.RETRYABLE_HTTP_CODES
    ):
        return True

    err_msg = str(e).upper()
    return any(keyword in err_msg for keyword in GeminiErrorKind.RETRYABLE_KEYWORDS)
