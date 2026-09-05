"""Gemini API 通信およびリトライ処理モジュールの単体テスト."""

import logging
from unittest.mock import MagicMock, patch

import pytest
from code_chat_cli.api import (
    _extract_retry_delay,
    _is_retryable_error,
    send_message_stream_with_retry,
    send_message_with_retry,
)
from google.genai.errors import APIError


@pytest.mark.parametrize(
    "error_message, expected_delay",
    [
        # Gemini API の実際のレスポンス形式: retryDelay: '32s' / '32.5s'
        ("Resource exhausted. retryDelay: '32s' Please wait.", 32.0),
        ("Resource exhausted. retryDelay: '32.5s' Please wait.", 32.5),
        # クォートなし表記: retryDelay: 10s
        ("Error occurred retryDelay: 10s in stream", 10.0),
        # retryDelay なし（Match しない）
        ("Quota exceeded without delay info", None),
        ("retryDelay: 'abc's", None),  # 秒数が数値でない
    ],
)
def test_extract_retry_delay_valid_and_invalid_patterns(error_message, expected_delay):
    """_extract_retry_delay が様々なエラーメッセージ形式から正しく秒数を抽出し, 不正な場合は None を返すか検証."""
    ex = Exception(error_message)
    assert _extract_retry_delay(ex) == expected_delay


def test_extract_retry_delay_value_error_handling(monkeypatch):
    """re.search でマッチしたものの float 変換時に ValueError が発生した場合に None を返す（except ValueError ルート）を検証."""
    mock_match = MagicMock()
    mock_match.group.return_value = "not_a_number"

    monkeypatch.setattr("re.search", lambda pattern, string: mock_match)

    ex = Exception("retryDelay: 'not_a_number's")
    assert _extract_retry_delay(ex) is None


@pytest.mark.parametrize(
    "error_message",
    [
        "ResourceHasExhausted: Quota exceeded for GenerateRequestsPerDay",
        "API limit reached: PerDay limit exceeded for this model.",
        "Error 429: Quota Exceeded (PerDay)",
    ],
)
def test_is_retryable_error_per_day_quota_returns_false(error_message, caplog):
    """1日あたりのクォータ超過 (RPD) の場合は False を返し, エラーログが出力されることを検証."""
    ex = Exception(error_message)

    with caplog.at_level(logging.ERROR):
        result = _is_retryable_error(ex)

    # 判定結果が False であること
    assert result is False

    # ログメッセージが出力されていること
    assert "1日あたりの API 利用上限 (RPD) に到達しました." in caplog.text


def test_is_retryable_error_value_error_fallback():
    """異常系: code 属性が数値に変換できない文字列（ValueError）の場合, メッセージ判定へフォールバックするか検証."""
    # code 属性に int() 変換できない文字列を設定
    error = APIError("503 Service Unavailable", {})
    error.code = "INVALID_CODE"

    # int(code) で ValueError が発生するが, 内部でキャッチされメッセージ文字列("503")から True と判定される
    assert _is_retryable_error(error) is True


def test_is_retryable_error_type_error_fallback():
    """異常系: code 属性が int() 変換不可な型（TypeError）の場合, メッセージ判定へフォールバックするか検証."""
    # code 属性に int() 変換できないリスト型を設定
    error = APIError("400 Bad Request", {})
    error.code = [503]

    # int(code) で TypeError が発生するが, 内部でキャッチされメッセージ("400")から False と判定される
    assert _is_retryable_error(error) is False


@patch("code_chat_cli.chat.time.sleep")
def test_send_message_with_retry_uses_api_retry_delay(mock_sleep):
    """異常系 (retryDelay 優先): エラーレスポンスに含まれる retryDelay 秒数が sleep に適用されるか検証."""
    mock_chat = MagicMock()
    mock_response = MagicMock(text="Success")

    # APIError クラスのインスタンスとして作成し, __str__ を明示的に設定
    err_with_delay = APIError("429 RESOURCE_EXHAUSTED retryDelay: '30s'", {})
    err_with_delay.__str__ = lambda: "429 RESOURCE_EXHAUSTED retryDelay: '30s'"

    mock_chat.send_message.side_effect = [err_with_delay, mock_response]

    res = send_message_with_retry(mock_chat, "hi", max_retries=3)

    assert res == mock_response
    # api_retry_delay + 1.0 秒（30.0 + 1.0 = 31.0）待機されることを検証
    mock_sleep.assert_called_once_with(31.0)


@patch("code_chat_cli.chat.time.sleep")
def test_send_message_with_retry_exceeds_max_retries(mock_sleep):
    """異常系 (上限超過): リトライ回数上限を超えて失敗した場合に例外が投げられるか検証."""
    mock_chat = MagicMock()
    mock_chat.send_message.side_effect = APIError("503 Service Unavailable", {})

    with pytest.raises(APIError):
        send_message_with_retry(mock_chat, "hi", max_retries=3, initial_delay=1.0)

    assert mock_chat.send_message.call_count == 3
    assert mock_sleep.call_count == 2


def test_send_message_with_retry_non_retryable_error():
    """異常系 (リトライ対象外): 400 Bad Request 等のリトライ不可エラーは即座に raise されるか検証."""
    mock_chat = MagicMock()
    mock_chat.send_message.side_effect = APIError("400 INVALID_ARGUMENT", {})

    with pytest.raises(APIError):
        send_message_with_retry(mock_chat, "hi", max_retries=3)

    # 1回目の実行で即座に中断されること
    assert mock_chat.send_message.call_count == 1


def test_send_message_with_retry_success_on_first_try():
    """正常系: 1回目の試行で正常にレスポンスが返るケースを検証."""
    mock_chat = MagicMock()
    mock_response = MagicMock(text="Hello")
    mock_chat.send_message.return_value = mock_response

    res = send_message_with_retry(mock_chat, "hi")

    assert res == mock_response
    mock_chat.send_message.assert_called_once_with("hi")


@patch("code_chat_cli.chat.time.sleep")
def test_send_message_with_retry_retry_and_succeed(mock_sleep):
    """異常系からの回復: 503 エラーが発生した後に2回目で成功するケースを検証."""
    mock_chat = MagicMock()
    mock_response = MagicMock(text="Hello after retry")

    # 1回目は 503 エラー, 2回目は成功
    mock_chat.send_message.side_effect = [
        APIError("503 Service Unavailable", {}),
        mock_response,
    ]

    res = send_message_with_retry(mock_chat, "hi", max_retries=3, initial_delay=1.0)

    assert res == mock_response
    assert mock_chat.send_message.call_count == 2
    mock_sleep.assert_called_once()


def test_send_message_stream_with_retry_success():
    """正常系: 1回目の試行で正常にストリームが返却されるか検証."""
    mock_chat = MagicMock()
    mock_chat.send_message_stream.return_value = iter(["chunk1", "chunk2"])

    result = send_message_stream_with_retry(mock_chat, "hello")

    assert list(result) == ["chunk1", "chunk2"]
    assert mock_chat.send_message_stream.call_count == 1


def test_send_message_stream_with_retry_503_retry_and_succeed(monkeypatch):
    """異常系 -> 正常系: 503 エラーが発生し, リトライ後に成功するか検証."""
    mock_chat = MagicMock()
    mock_stream = iter(["success_chunk"])

    # APIError の生成 (第一引数: message, 第二引数: response_json)
    error_503 = APIError("503 Service Unavailable", {})
    error_503.code = 503
    mock_chat.send_message_stream.side_effect = [error_503, mock_stream]

    # time.sleep の実行を記録＆スキップ
    sleep_calls = []
    monkeypatch.setattr("time.sleep", sleep_calls.append)

    result = send_message_stream_with_retry(
        mock_chat, "hello", max_retries=3, initial_delay=2.5
    )

    assert list(result) == ["success_chunk"]
    assert mock_chat.send_message_stream.call_count == 2
    assert sleep_calls == [2.5]  # 初回ディレイが適用されていること


def test_send_message_stream_with_retry_exceeds_max_retries(monkeypatch):
    """異常系: リトライ上限（max_retries）を超えて APIError が送出されるか検証."""
    mock_chat = MagicMock()
    error_429 = APIError("429 Too Many Requests", {})
    error_429.code = 429
    mock_chat.send_message_stream.side_effect = error_429

    sleep_calls = []
    monkeypatch.setattr("time.sleep", sleep_calls.append)

    with pytest.raises(APIError) as exc_info:
        list(
            send_message_stream_with_retry(
                mock_chat, "hello", max_retries=3, initial_delay=1.0
            )
        )

    assert getattr(exc_info.value, "code", None) == 429
    assert mock_chat.send_message_stream.call_count == 3
    # 指数バックオフ（1.0s, 2.0s）で2回スリープされたこと
    assert sleep_calls == [1.0, 2.0]


def test_send_message_stream_with_retry_non_retryable_error():
    """異常系: 503/429 以外のエラー（例: 400 Bad Request）が発生した場合, リトライせず即座に例外を送出するか検証."""
    mock_chat = MagicMock()
    error_400 = APIError("400 Bad Request", {})
    error_400.code = 400
    mock_chat.send_message_stream.side_effect = error_400

    with pytest.raises(APIError) as exc_info:
        # ジェネレータを評価・消費して例外を発生させる
        list(send_message_stream_with_retry(mock_chat, "hello"))

    assert getattr(exc_info.value, "code", None) == 400
    assert mock_chat.send_message_stream.call_count == 1


def test_send_message_stream_with_retry_error_during_iteration(monkeypatch):
    """異常系: イテレーション（データ受信）の最初で 503 エラーが発生し, リトライして成功するか検証."""
    mock_chat = MagicMock()

    # 1回目のイテレーション（__iter__）で APIError を発生させる例外イテレータ
    class ErrorStream:  # pylint: disable=too-few-public-methods
        """テスト用モックストリームクラス.

        イテレーションの開始時（`__iter__` 呼び出し時）に即座に APIError を送出することで,
        レスポンス取得ループ（`for chunk in response_stream`）の開始直後に発生する
        通信エラーの挙動をシミュレートします.
        """

        def __iter__(self):
            raise APIError("503 Service Unavailable", {})

    mock_chat.send_message_stream.side_effect = [
        ErrorStream(),
        ["success_chunk"],
    ]

    sleep_calls = []
    monkeypatch.setattr("time.sleep", sleep_calls.append)

    result = list(send_message_stream_with_retry(mock_chat, "hello", max_retries=3))

    assert result == ["success_chunk"]
    assert len(sleep_calls) == 1  # 1回リトライされたこと


def test_send_message_stream_with_retry_error_after_yielding_chunks():
    """異常系: 途中でチャンクを出力した後にエラーが発生した場合, リトライせずに即座に例外を送出するか検証."""
    mock_chat = MagicMock()

    # 1つ目のチャンクを出力したあとに例外を投げるジェネレータ
    def partial_stream():
        yield "first_chunk"
        raise APIError("503 Service Unavailable", {})

    mock_chat.send_message_stream.return_value = partial_stream()

    with pytest.raises(APIError):
        # 途中まで取得してから例外が発生することを確認
        gen = send_message_stream_with_retry(mock_chat, "hello", max_retries=3)
        assert next(gen) == "first_chunk"
        next(gen)  # ここで例外送出

    # リトライされずに呼び出し回数が 1 回であることを検証
    assert mock_chat.send_message_stream.call_count == 1


@patch("code_chat_cli.chat.time.sleep")
def test_send_message_stream_with_retry_uses_api_retry_delay(mock_sleep):
    """ストリーミング異常系 (retryDelay 優先): エラーレスポンスの retryDelay 秒数が sleep に適用されるか検証."""
    mock_chat = MagicMock()
    mock_chunk = MagicMock(text="stream_chunk")

    # 1回目の呼び出しで retryDelay 付きの例外, 2回目で正常なイテレータを返す
    err_with_delay = APIError("429 RESOURCE_EXHAUSTED retryDelay: '30s'", {})
    err_with_delay.__str__ = lambda: "429 RESOURCE_EXHAUSTED retryDelay: '30s'"

    mock_chat.send_message_stream.side_effect = [
        err_with_delay,
        [mock_chunk],
    ]

    gen = send_message_stream_with_retry(mock_chat, "hi", max_retries=3)
    chunks = list(gen)

    # 最終的に正常なチャンクが取得できること
    assert chunks == [mock_chunk]

    # api_retry_delay + 1.0 秒（30.0 + 1.0 = 31.0）で sleep が呼ばれたこと
    mock_sleep.assert_called_once_with(31.0)
