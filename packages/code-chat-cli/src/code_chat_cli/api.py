"""Gemini API 通信およびリトライ処理を行うモジュール."""

import logging
import re
import time
from collections.abc import Iterator
from typing import Any

from google.genai.errors import APIError, ClientError, ServerError

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

        except Exception as e:  # noqa: BLE001 # pylint: disable=broad-exception-caught
            last_exception = e
            if attempt == max_retries or not _is_retryable_error(e):
                break

            api_retry_delay = _extract_retry_delay(e)
            if api_retry_delay is not None:
                sleep_time = api_retry_delay + 1.0
            else:
                sleep_time = delay
                delay *= backoff_factor

            logger.warning(
                "Gemini API で一時的なエラーが発生しました (%d/%d): %s. %.1f秒後に再試行します...",
                attempt,
                max_retries,
                e,
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
        APIError: 最大リトライ回数を超えてエラーが発生した場合.
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

        except Exception as e:  # pylint: disable=broad-exception-caught
            # 既にユーザーに画面出力が開始されている途中で切れた場合は,
            # 出力の重複を防ぐためリトライせずにエラーを送出する
            if (
                has_yielded_content
                or attempt == max_retries
                or not _is_retryable_error(e)
            ):
                error_detail = (
                    str(e) if logger.isEnabledFor(logging.DEBUG) else type(e).__name__
                )
                logger.error(
                    "ストリーミングの受信途中でエラーが発生しました（一部出力済みのためリトライ中断）: %s",
                    error_detail,
                )
                raise

            # API側から retryDelay の指定があれば優先, なければ指数バックオフ
            api_retry_delay = _extract_retry_delay(e)
            if api_retry_delay is not None:
                sleep_time = api_retry_delay + 1.0
            else:
                sleep_time = delay
                delay *= backoff_factor

            logger.warning(
                "Gemini API で一時的なエラーが発生しました (%d/%d): %s. %.1f秒後に再試行します...",
                attempt,
                max_retries,
                e,
                sleep_time,
            )
            time.sleep(sleep_time)


def _extract_retry_delay(e: Exception) -> float | None:
    """APIのエラー詳細情報 (RetryInfo) から推奨待機時間 (秒) を抽出します.

    Args:
        e (Exception): 発生した例外オブジェクト.

    Returns:
        float | None: 抽出された推奨待機秒数. 抽出できない場合は None.
    """
    err_str = str(e)
    match = re.search(r"retryDelay[\"']?\s*:\s*[\"']?(\d+(?:\.\d+)?)s", err_str)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return None


def _is_retryable_error(e: Exception) -> bool:
    """リトライ対象のエラー（503/429等）かどうかを判定します.

    Args:
        e (Exception): 検証対象の Gemini API 例外オブジェクト.

    Returns:
        bool: リトライ対象のエラーである場合は True, 400 Bad Request 等のリトライ不可エラーの場合は False.
    """
    err_str = str(e)

    # 1日あたりのクォータ超過 (RPD) は待機しても回復しないためリトライしない
    if "PerDay" in err_str or "GenerateRequestsPerDay" in err_str:
        logger.error("1日あたりの API 利用上限 (RPD) に到達しました.")
        return False

    # APIError, ServerError, ClientError すべてを対象
    if isinstance(e, (APIError, ServerError, ClientError)):
        code = getattr(e, "code", None) or getattr(e, "status_code", None)
        if code in (503, 429):
            return True

    err_msg = str(e).upper()
    return any(
        keyword in err_msg
        for keyword in ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED")
    )
