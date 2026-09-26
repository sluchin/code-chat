"""Gemini API 通信およびリトライ処理を行うモジュール.

Gemini API の呼び出しは, すべて `call_with_retry` を通して, リトライの方針を 1 か所に集約します.
SDK (`google-genai`) 自身のリトライは, 二重にリトライしないよう, 無効のままにします.
"""

from collections.abc import Callable, Iterable, Iterator
from typing import Any

import httpx
from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from code_chat_cli.gemini_error import (
    find_api_error,
    find_cause,
    is_daily_quota_error,
    retry_delay_seconds,
    summarize_error,
)
from code_chat_cli.gemini_error_kind import GeminiErrorKind
from code_chat_cli.logger import get_logger
from code_chat_cli.retry_policy import RetryPolicy

logger = get_logger(__name__)

# 待ち時間の既定 (指数バックオフ + ジッター). API が推奨待機時間を返した場合は, そちらを優先する
_BACKOFF = wait_exponential_jitter(
    initial=RetryPolicy.INITIAL_DELAY,
    max=RetryPolicy.MAX_DELAY,
    exp_base=RetryPolicy.EXP_BASE,
    jitter=RetryPolicy.JITTER,
)

# ストリームが最初のチャンクを返す前に終了したことを表す目印
_STREAM_END = object()


def call_with_retry(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Gemini API の呼び出しを実行し, 一時的なエラーの場合は, 待ってからリトライします.

    リトライの対象は, 503 / 429 (1 日あたりの上限を除く) と, ネットワークの一時的なエラーです.
    待ち時間は, API が推奨待機時間 (`retryDelay`) を返した場合はそれに従い, 返さない場合は
    指数バックオフにジッターを加えて決めます. 待機に入る前に, 原因と回数を警告として出力します.

    Args:
        func (Callable[..., Any]): 実行する Gemini API の呼び出し.
        *args (Any): `func` に渡す位置引数.
        **kwargs (Any): `func` に渡すキーワード引数.

    Returns:
        Any: `func` の戻り値.

    Raises:
        Exception: リトライの対象外のエラー, または最大試行回数を超えてエラーが続いた場合の,
            最後のエラー.

    """
    retrying = Retrying(
        stop=stop_after_attempt(RetryPolicy.MAX_ATTEMPTS),
        retry=retry_if_exception(_is_retryable_error),
        wait=_wait_seconds,
        before_sleep=_log_retry,
        reraise=True,
    )
    return retrying(func, *args, **kwargs)


def send_message_with_retry(chat: Any, prompt: str) -> Any:
    """Gemini API へのリクエストを送信し, 一時的なエラー発生時にリトライを行います.

    Args:
        chat (Any): Gemini Chat インスタンス.
        prompt (str): 送信するプロンプト文字列.

    Returns:
        Any: Gemini API からのレスポンス.

    """
    return call_with_retry(chat.send_message, prompt)


def send_message_stream_with_retry(chat: Any, prompt: str) -> Iterator[Any]:
    """Gemini API へのストリーミングリクエストを送信し, 一時的なエラー発生時にリトライを行います.

    リトライの対象は, 最初のチャンクを受信するまでです (`stream_with_retry` を参照).

    Args:
        chat (Any): Gemini Chat インスタンス.
        prompt (str): 送信するプロンプト文字列.

    Returns:
        Iterator[Any]: Gemini API からのレスポンスチャンク.

    """
    return stream_with_retry(chat.send_message_stream, prompt)


def stream_with_retry(
    func: Callable[..., Iterable[Any]], *args: Any, **kwargs: Any
) -> Iterator[Any]:
    """ストリーミングの呼び出しを実行し, 一時的なエラー発生時にリトライを行います.

    リトライの対象は, 最初のチャンクを受信するまでです. 出力が始まったあとにエラーが発生した
    場合は, 出力の重複を防ぐため, リトライせずにエラーを送出します.

    Args:
        func (Callable[..., Iterable[Any]]): チャンクを返す, Gemini API の呼び出し.
        *args (Any): `func` に渡す位置引数.
        **kwargs (Any): `func` に渡すキーワード引数.

    Yields:
        Any: `func` が返すチャンク.

    Raises:
        Exception: 出力が始まったあとに, Gemini API のエラーが発生した場合.

    """
    first, stream = call_with_retry(_open_stream, func, *args, **kwargs)
    if first is _STREAM_END:
        return

    try:
        yield first
        yield from stream
    # LangChain など, ライブラリが Gemini API のエラーを別の例外で包む場合があるため,
    # 例外の種類を問わず捕捉して, Gemini API のエラーの場合のみログに記録し, 再送出する.
    except Exception as e:
        if find_api_error(e) is not None:
            logger.error(
                "ストリーミングの受信途中でエラーが発生しました (一部出力済みのため, リトライせずに中断します)"
            )
        raise


def _open_stream(
    func: Callable[..., Iterable[Any]], *args: Any, **kwargs: Any
) -> tuple[Any, Iterator[Any]]:
    """ストリームを開き, 最初のチャンクまで受信します (リクエストは, 最初の受信で実行される).

    Args:
        func (Callable[..., Iterable[Any]]): チャンクを返す, Gemini API の呼び出し.
        *args (Any): `func` に渡す位置引数.
        **kwargs (Any): `func` に渡すキーワード引数.

    Returns:
        tuple[Any, Iterator[Any]]: (最初のチャンク, 残りのストリーム).
            最初のチャンクを受信する前にストリームが終了した場合は, 最初のチャンクが `_STREAM_END`.

    """
    stream = iter(func(*args, **kwargs))
    return next(stream, _STREAM_END), stream


def _is_retryable_error(e: BaseException) -> bool:
    """リトライ対象のエラー (503 / 429 / ネットワークの一時的なエラー) かどうかを判定します.

    Args:
        e (BaseException): 検証対象の例外.

    Returns:
        bool: リトライ対象のエラーである場合は True. 400 Bad Request 等のリトライ不可のエラーと,
            待っても回復しない 1 日あたりの上限 (RPD) は False.

    """
    # LangChain など, ライブラリが例外を別の例外で包んでいる場合も対象にする
    if find_cause(e, httpx.TransportError) is not None:
        return True
    api_error = find_api_error(e)
    if api_error is None:
        return False

    # 1日あたりのクォータ超過 (RPD) は待機しても回復しないためリトライしない
    if is_daily_quota_error(api_error):
        return False

    if api_error.code in GeminiErrorKind.RETRYABLE_HTTP_CODES:
        return True

    err_msg = str(api_error).upper()
    return any(keyword in err_msg for keyword in GeminiErrorKind.RETRYABLE_KEYWORDS)


def _wait_seconds(retry_state: RetryCallState) -> float:
    """次のリトライまでの待ち時間 (秒) を決めます.

    Args:
        retry_state (RetryCallState): tenacity が保持するリトライの状態.

    Returns:
        float: API が推奨待機時間 (`retryDelay`) を返した場合は, それに余裕を加えた秒数.
            返さない場合は, 指数バックオフにジッターを加えた秒数.

    """
    error = retry_state.outcome.exception() if retry_state.outcome else None
    # 包まれた例外の文字列には, retryDelay が含まれない場合があるため, APIError を取り出す
    api_error = find_api_error(error)
    delay = retry_delay_seconds(api_error) if api_error else None
    if delay is not None:
        return delay + RetryPolicy.RETRY_DELAY_MARGIN
    return float(_BACKOFF(retry_state))


def _log_retry(retry_state: RetryCallState) -> None:
    """リトライの待機に入る前に, 原因・回数・待ち時間を警告として出力します.

    Args:
        retry_state (RetryCallState): tenacity が保持するリトライの状態.

    """
    error = retry_state.outcome.exception() if retry_state.outcome else None
    api_error = find_api_error(error)
    if api_error is not None:
        cause = summarize_error(api_error)
    else:
        cause = f"{type(error).__name__}: {error}"
    sleep = retry_state.next_action.sleep if retry_state.next_action else 0.0
    logger.warning(
        "Gemini API で一時的なエラーが発生しました (%d/%d): %s. %.1f秒後に再試行します...",
        retry_state.attempt_number,
        RetryPolicy.MAX_ATTEMPTS,
        cause,
        sleep,
    )
