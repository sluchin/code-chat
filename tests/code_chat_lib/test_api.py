"""Gemini API 通信およびリトライ処理モジュールの単体テスト."""

import logging
from unittest.mock import MagicMock

import httpx
import pytest
from google.genai.errors import APIError
from tenacity import RetryCallState
from tenacity.wait import wait_base

from code_chat_lib.api import (
    _STREAM_END,
    _is_retryable_error,
    _log_retry,
    _open_stream,
    _wait_seconds,
    call_with_retry,
    send_message_stream_with_retry,
    send_message_with_retry,
    stream_with_retry,
)
from code_chat_lib.retry_policy import RetryPolicy


def _api_error(code, status="UNAVAILABLE", message="high demand", extra=None):
    """Gemini API の実際のレスポンス形式に近い APIError を作成する."""
    body = {"error": {"code": code, "status": status, "message": message}}
    if extra:
        body["error"]["details"] = extra
    return APIError(code, body)


def _retry_state(error=None, sleep=None):
    """tenacity のリトライの状態 (例外と, 次の待機時間) を模した RetryCallState を作成する."""
    state = RetryCallState(retry_object=MagicMock(), fn=None, args=(), kwargs={})
    if error is not None:
        state.set_exception((type(error), error, None))
    if sleep is not None:
        state.next_action = MagicMock(sleep=sleep)
    return state


class TestCallWithRetry:
    """`call_with_retry` のテスト."""

    def test_call_with_retry_success(self, no_retry_sleep):
        """1 回目で成功した場合は, 待たずに戻り値を返し, 引数がそのまま渡されるか検証."""
        func = MagicMock(return_value="ok")

        result = call_with_retry(func, "a", key="b")

        assert result == "ok"
        func.assert_called_once_with("a", key="b")
        no_retry_sleep.assert_not_called()

    def test_call_with_retry_exceeds_max_attempts_failure(self, no_retry_sleep):
        """一時的なエラーが続いた場合は, 最大試行回数で諦め, 最後のエラーを送出するか検証."""
        func = MagicMock(side_effect=_api_error(503))

        with pytest.raises(APIError):
            call_with_retry(func)

        assert func.call_count == RetryPolicy.MAX_ATTEMPTS
        assert no_retry_sleep.call_count == RetryPolicy.MAX_ATTEMPTS - 1

    def test_call_with_retry_non_retryable_failure(self, no_retry_sleep):
        """リトライ対象外のエラー (400 など) は, 待たずに即座に送出されるか検証."""
        func = MagicMock(side_effect=_api_error(400, "INVALID_ARGUMENT", "bad"))

        with pytest.raises(APIError):
            call_with_retry(func)

        func.assert_called_once()
        no_retry_sleep.assert_not_called()

    def test_call_with_retry_daily_quota_failure(self, no_retry_sleep):
        """1 日あたりの上限 (RPD) は, 待っても回復しないため, リトライせずに送出されるか検証."""
        error = _api_error(
            429,
            "RESOURCE_EXHAUSTED",
            "quota",
            [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel"}]}],
        )
        func = MagicMock(side_effect=error)

        with pytest.raises(APIError):
            call_with_retry(func)

        func.assert_called_once()
        no_retry_sleep.assert_not_called()

    def test_call_with_retry_retry_exception(self, no_retry_sleep):
        """一時的なエラー (503) の場合は, 指数バックオフで待ってリトライし, 成功すれば結果を返すか検証."""
        func = MagicMock(side_effect=[_api_error(503), _api_error(503), "ok"])

        result = call_with_retry(func)

        assert result == "ok"
        assert func.call_count == 3
        waits = [c.args[0] for c in no_retry_sleep.call_args_list]
        # 1 回目は 1 秒, 2 回目は 2 秒を基準に, ジッター (最大 1 秒) が加わる
        assert 1.0 <= waits[0] < 1.0 + RetryPolicy.JITTER
        assert 2.0 <= waits[1] < 2.0 + RetryPolicy.JITTER

    def test_call_with_retry_uses_api_retry_delay_exception(self, no_retry_sleep):
        """API が推奨待機時間 (retryDelay) を返した場合は, それに余裕を加えた秒数だけ待つか検証."""
        error = _api_error(
            429,
            "RESOURCE_EXHAUSTED",
            "quota",
            [{"retryDelay": "30s"}],
        )
        func = MagicMock(side_effect=[error, "ok"])

        assert call_with_retry(func) == "ok"

        no_retry_sleep.assert_called_once_with(30.0 + RetryPolicy.RETRY_DELAY_MARGIN)

    def test_call_with_retry_transport_error_exception(self, no_retry_sleep):
        """ネットワークの一時的なエラー (接続失敗) も, リトライされるか検証."""
        func = MagicMock(side_effect=[httpx.ConnectError("refused"), "ok"])

        assert call_with_retry(func) == "ok"

        assert func.call_count == 2
        no_retry_sleep.assert_called_once()

    def test_call_with_retry_logs_warning_exception(self, caplog):
        """待機に入る前に, 原因と回数が警告として出力されるか検証 (無言で待たない)."""
        func = MagicMock(side_effect=[_api_error(503), "ok"])

        call_with_retry(func)

        assert "一時的なエラーが発生しました (1/5)" in caplog.text
        assert "[HTTP 503 UNAVAILABLE]" in caplog.text
        assert "秒後に再試行します" in caplog.text


class TestSendMessageWithRetry:
    """`send_message_with_retry` のテスト."""

    def test_send_message_with_retry_success(self):
        """プロンプトが送信され, レスポンスが返るか検証."""
        chat = MagicMock()

        result = send_message_with_retry(chat, "hi")

        assert result is chat.send_message.return_value
        chat.send_message.assert_called_once_with("hi")

    def test_send_message_with_retry_retry_exception(self):
        """一時的なエラーの場合は, リトライされて成功するか検証."""
        chat = MagicMock()
        chat.send_message.side_effect = [_api_error(503), "response"]

        assert send_message_with_retry(chat, "hi") == "response"

        assert chat.send_message.call_count == 2


class TestSendMessageStreamWithRetry:
    """`send_message_stream_with_retry` のテスト."""

    def test_send_message_stream_with_retry_success(self):
        """すべてのチャンクが, 順に返されるか検証."""
        chat = MagicMock()
        chat.send_message_stream.return_value = iter(["chunk1", "chunk2", "chunk3"])

        assert list(send_message_stream_with_retry(chat, "hi")) == [
            "chunk1",
            "chunk2",
            "chunk3",
        ]
        chat.send_message_stream.assert_called_once_with("hi")

    def test_send_message_stream_with_retry_error_after_yielding_chunks_failure(
        self, caplog
    ):
        """出力が始まったあとのエラーは, 出力の重複を避けるため, リトライせずに送出されるか検証."""
        chat = MagicMock()

        def partial_stream():
            yield "first_chunk"
            raise _api_error(503)

        chat.send_message_stream.return_value = partial_stream()

        gen = send_message_stream_with_retry(chat, "hello")
        assert next(gen) == "first_chunk"
        with pytest.raises(APIError):
            next(gen)

        assert chat.send_message_stream.call_count == 1
        assert "一部出力済みのため" in caplog.text

    def test_send_message_stream_with_retry_non_retryable_error_failure(self):
        """最初のチャンクの前に, リトライ対象外のエラーが発生した場合は, 即座に送出されるか検証."""
        chat = MagicMock()

        def failing_stream():
            raise _api_error(400, "INVALID_ARGUMENT", "bad")
            yield  # pylint: disable=unreachable  # ジェネレータにするために必要

        chat.send_message_stream.return_value = failing_stream()

        with pytest.raises(APIError):
            list(send_message_stream_with_retry(chat, "hello"))

        assert chat.send_message_stream.call_count == 1

    def test_send_message_stream_with_retry_retry_exception(self):
        """最初のチャンクの前に, 一時的なエラーが発生した場合は, リトライされて成功するか検証."""
        chat = MagicMock()

        def failing_stream():
            raise _api_error(503)
            yield  # pylint: disable=unreachable  # ジェネレータにするために必要

        chat.send_message_stream.side_effect = [failing_stream(), iter(["ok"])]

        assert list(send_message_stream_with_retry(chat, "hello")) == ["ok"]

        assert chat.send_message_stream.call_count == 2

    def test_send_message_stream_with_retry_request_error_exception(self):
        """ストリームを開く呼び出し自体が, 一時的なエラーで失敗した場合も, リトライされるか検証."""
        chat = MagicMock()
        chat.send_message_stream.side_effect = [_api_error(503), iter(["ok"])]

        assert list(send_message_stream_with_retry(chat, "hello")) == ["ok"]

    def test_send_message_stream_with_retry_empty_stream(self):
        """チャンクが 1 つも無いストリームは, 何も返さずに終了するか検証."""
        chat = MagicMock()
        chat.send_message_stream.return_value = iter([])

        assert not list(send_message_stream_with_retry(chat, "hello"))


class TestStreamWithRetry:
    """`stream_with_retry` のテスト."""

    def test_stream_with_retry_success(self):
        """任意の呼び出しが返すチャンクが, 引数とともに呼ばれて, 順に返されるか検証."""
        func = MagicMock(return_value=iter(["a", "b"]))

        assert list(stream_with_retry(func, {"q": 1}, key="v")) == ["a", "b"]
        func.assert_called_once_with({"q": 1}, key="v")

    def test_stream_with_retry_wrapped_error_after_yielding_chunks_failure(
        self, caplog
    ):
        """APIError を別の例外で包んだエラーも, 出力後は, リトライせずに送出されるか検証."""

        def partial_stream():
            yield "first_chunk"
            raise RuntimeError("wrapped") from _api_error(503)

        func = MagicMock(return_value=partial_stream())

        gen = stream_with_retry(func)
        assert next(gen) == "first_chunk"
        with pytest.raises(RuntimeError):
            next(gen)

        assert func.call_count == 1
        assert "一部出力済みのため" in caplog.text

    def test_stream_with_retry_non_api_error_after_yielding_chunks_failure(
        self, caplog
    ):
        """Gemini API と無関係のエラーは, 出力後に, ログを出さずに送出されるか検証."""

        def partial_stream():
            yield "first_chunk"
            raise ValueError("bad")

        gen = stream_with_retry(MagicMock(return_value=partial_stream()))
        assert next(gen) == "first_chunk"
        with pytest.raises(ValueError):
            next(gen)

        assert "一部出力済みのため" not in caplog.text

    def test_stream_with_retry_wrapped_error_retry_exception(self):
        """APIError を別の例外で包んだ一時的なエラーも, 最初のチャンクの前ならリトライされるか検証."""
        wrapped = RuntimeError("wrapped")
        wrapped.__cause__ = _api_error(503)
        func = MagicMock(side_effect=[wrapped, iter(["ok"])])

        assert list(stream_with_retry(func)) == ["ok"]

        assert func.call_count == 2


class TestOpenStream:
    """`_open_stream` のテスト."""

    def test_open_stream_success(self):
        """最初のチャンクと, 残りのストリームが返るか検証."""
        func = MagicMock(return_value=["a", "b"])

        first, stream = _open_stream(func, "hi", key="v")

        assert first == "a"
        assert list(stream) == ["b"]
        func.assert_called_once_with("hi", key="v")

    def test_open_stream_empty(self):
        """チャンクが無い場合は, 最初のチャンクが終了の目印になるか検証."""
        first, _ = _open_stream(MagicMock(return_value=[]))

        assert first is _STREAM_END


class TestIsRetryableError:
    """`_is_retryable_error` のテスト."""

    @pytest.mark.parametrize("code", [503, 429])
    def test_is_retryable_error_success(self, code):
        """503 / 429 は, リトライ対象になるか検証."""
        assert _is_retryable_error(_api_error(code)) is True

    def test_is_retryable_error_transport_error_success(self):
        """ネットワークの一時的なエラーは, リトライ対象になるか検証."""
        assert _is_retryable_error(httpx.ReadTimeout("timeout")) is True

    @pytest.mark.parametrize(
        "error",
        [
            httpx.ProxyError("proxy"),
            httpx.UnsupportedProtocol("no scheme"),
            httpx.LocalProtocolError("bad request"),
        ],
    )
    def test_is_retryable_error_config_transport_error_failure(self, error):
        """プロキシや URL の設定の誤りなど, 待っても直らないネットワークのエラーは, リトライ対象にならないか検証."""
        assert _is_retryable_error(error) is False

    def test_is_retryable_error_wrapped_transport_error_success(self):
        """ネットワークの一時的なエラーを別の例外で包んだエラーも, リトライ対象になるか検証."""
        wrapped = RuntimeError("wrapped")
        wrapped.__cause__ = httpx.ConnectError("refused")

        assert _is_retryable_error(wrapped) is True

    def test_is_retryable_error_wrapped_error_success(self):
        """APIError を別の例外で包んだエラーも, 原因が 503 ならリトライ対象になるか検証."""
        wrapped = RuntimeError("wrapped")
        wrapped.__cause__ = _api_error(503)

        assert _is_retryable_error(wrapped) is True

    @pytest.mark.parametrize("bad_code", ["not_a_number", object()])
    def test_is_retryable_error_code_fallback_exception(self, bad_code):
        """code が整数として比較できない場合は, エラー文のキーワードで判定するか検証."""
        error = _api_error(503)
        error.code = bad_code

        assert _is_retryable_error(error) is True

    @pytest.mark.parametrize(
        "error",
        [
            _api_error(400, "INVALID_ARGUMENT", "bad"),
            _api_error(404, "NOT_FOUND", "no model"),
            ValueError("429"),
        ],
    )
    def test_is_retryable_error_not_retryable(self, error):
        """リトライ不可のエラー (400 / 404 / Gemini API 以外の例外) は, 対象外になるか検証."""
        assert _is_retryable_error(error) is False

    @pytest.mark.parametrize(
        "error_message",
        [
            "ResourceHasExhausted: Quota exceeded for GenerateRequestsPerDay",
            "API limit reached: PerDay limit exceeded for this model.",
        ],
    )
    def test_is_retryable_error_per_day_quota_returns_false(self, error_message):
        """1日あたりのクォータ超過 (RPD) の場合は, 待っても回復しないため False を返すか検証."""
        error = _api_error(429, "RESOURCE_EXHAUSTED", error_message)

        assert _is_retryable_error(error) is False


class TestWaitSeconds:
    """`_wait_seconds` のテスト."""

    def test_wait_seconds_backoff_success(self):
        """推奨待機時間が無い場合は, 指数バックオフにジッターを加えた秒数になるか検証."""
        state = _retry_state(_api_error(503))

        assert 1.0 <= _wait_seconds(state) < 1.0 + RetryPolicy.JITTER

    def test_wait_seconds_retry_delay_success(self):
        """推奨待機時間 (retryDelay) がある場合は, それに余裕を加えた秒数になるか検証."""
        error = _api_error(429, "RESOURCE_EXHAUSTED", "q", [{"retryDelay": "12s"}])

        assert (
            _wait_seconds(_retry_state(error)) == 12.0 + RetryPolicy.RETRY_DELAY_MARGIN
        )

    def test_wait_seconds_wrapped_retry_delay_success(self):
        """APIError を別の例外で包んだエラーでも, 原因の推奨待機時間に従うか検証."""
        wrapped = RuntimeError("wrapped")
        wrapped.__cause__ = _api_error(
            429, "RESOURCE_EXHAUSTED", "q", [{"retryDelay": "7s"}]
        )

        assert (
            _wait_seconds(_retry_state(wrapped)) == 7.0 + RetryPolicy.RETRY_DELAY_MARGIN
        )

    def test_wait_seconds_without_outcome(self):
        """例外が記録されていない状態でも, 指数バックオフの秒数が返るか検証."""
        assert isinstance(_wait_seconds(_retry_state()), float)


class TestLogRetry:
    """`_log_retry` のテスト."""

    def test_log_retry_api_error_success(self, caplog):
        """Gemini API のエラーは, 概要・回数・待ち時間が警告として出力されるか検証."""
        state = _retry_state(_api_error(503), sleep=2.5)

        _log_retry(state)

        assert "(1/5)" in caplog.text
        assert "[HTTP 503 UNAVAILABLE]" in caplog.text
        assert "2.5秒後に再試行します" in caplog.text

    def test_log_retry_other_error_success(self, caplog):
        """Gemini API 以外のエラー (ネットワークなど) は, 例外名とメッセージが出力されるか検証."""
        state = _retry_state(httpx.ConnectError("refused"), sleep=1.0)

        _log_retry(state)

        assert "ConnectError: refused" in caplog.text

    def test_log_retry_without_state(self, caplog):
        """例外と待機時間が記録されていない状態でも, 警告が出力されるか検証."""
        with caplog.at_level(logging.WARNING):
            _log_retry(_retry_state())

        assert "再試行します" in caplog.text


def test_backoff_is_tenacity_wait():
    """既定の待ち時間 (指数バックオフ + ジッター) が, tenacity の待機として組み立てられているか検証."""
    from code_chat_lib import api  # pylint: disable=import-outside-toplevel

    assert isinstance(api._BACKOFF, wait_base)  # pylint: disable=protected-access
