# pylint: disable=too-many-lines, disable=redefined-outer-name
"""`code_chat_cli.chat` モジュールのCLI引数解析, 対話セッション, エラーハンドリングのテスト."""

import io
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from code_chat_cli.api import (
    _extract_retry_delay,
    _is_retryable_error,
    send_message_stream_with_retry,
    send_message_with_retry,
)
from code_chat_cli.chat import (
    apply_file_modification,
    handle_write_mode_confirmation,
    is_partial_code,
    main,
    save_chat_history,
)
from google.genai.errors import APIError


@pytest.fixture
def mock_gemini_client():
    """Gemini Client および Chat セッションのモックを作成."""
    with patch("code_chat_cli.chat.get_gemini_client") as mock_get_client:
        mock_client = MagicMock()
        mock_chat = MagicMock()

        # ストリーミングレスポンス（イテレータ）のモック
        mock_chunk = MagicMock()
        mock_chunk.text = "モックされたAIからの回答です."
        mock_chat.send_message_stream.return_value = [mock_chunk]

        # 通常送信のレスポンスのモック
        mock_response = MagicMock()
        mock_response.text = "コンテキスト受信完了"
        mock_chat.send_message.return_value = mock_response

        mock_client.chats.create.return_value = mock_chat
        mock_get_client.return_value = mock_client

        yield {
            "get_client": mock_get_client,
            "client": mock_client,
            "chat": mock_chat,
        }


@pytest.fixture
def mock_args():
    """parse_args の全属性を網羅した SimpleNamespace モック."""
    with patch("code_chat_cli.chat.parse_args") as mock_parse:
        args = SimpleNamespace(
            debug=False,
            log_level="INFO",
            write_mode=False,
            model="gemini-flash-latest",
            context=None,
            prompt=None,
            output_path=None,
            target_path=None,
            auto_save=False,
            list_models=False,
            generate_commit_msg=False,
            review=False,
            staged=False,
        )
        mock_parse.return_value = args
        yield mock_parse


@pytest.mark.parametrize(
    "code_input",
    [
        "// ...",
        "//...",
        "# ...",
        "#...",
        "# 既存のコード",
        "// 既存のコード",
        "// 変更なし",
        "# 変更なし",
        "// rest of code",
        "# REST OF CODE",  # 大文字小文字（re.IGNORECASE）の検証
    ],
)
def test_is_partial_code_returns_true(code_input):
    """省略表現やプレースホルダーコメントが含まれている場合, True が返るか検証."""
    sample_code = f"""
def main():
    {code_input}
    return 0
"""
    assert is_partial_code(sample_code) is True


def test_is_partial_code_returns_false():
    """省略表現が含まれない完全なソースコードの場合, False が返るか検証."""
    complete_code = """
def add(a: int, b: int) -> int:
    # 2つの数値の和を計算する
    return a + b
"""
    assert is_partial_code(complete_code) is False


def test_apply_file_modification_success(tmp_path):
    """正常系: .bak バックアップが作成され, 元ファイルが新しい内容で上書きされるか検証."""
    target_file = tmp_path / "sample.py"
    target_file.write_text("original_code", encoding="utf-8")

    new_code = "updated_code"
    apply_file_modification(str(target_file), new_code)

    # バックアップファイル (.py.bak) が作成され, 元の内容が保存されていること
    bak_file = tmp_path / "sample.py.bak"
    assert bak_file.exists()
    assert bak_file.read_text(encoding="utf-8") == "original_code"

    # 対象ファイルが新しいコードで更新されていること
    assert target_file.read_text(encoding="utf-8") == new_code


def test_apply_file_modification_not_a_file(tmp_path):
    """異常系: パスが存在しない, またはディレクトリの場合, 早期リターンして何も処理しないか検証."""
    non_existent_file = tmp_path / "non_existent.py"

    # 存在しないパスを指定（ログを出力して終了）
    apply_file_modification(str(non_existent_file), "new_code")

    bak_file = tmp_path / "non_existent.py.bak"
    assert not non_existent_file.exists()
    assert not bak_file.exists()


def test_apply_file_modification_exception(tmp_path):
    """異常系: 書き込み時に Exception が発生した場合, except ブロックでキャッチされログが出力されるか検証."""
    target_file = tmp_path / "sample.py"
    target_file.write_text("original_code", encoding="utf-8")

    # read_text または write_text で例外を発生させる
    with patch.object(Path, "write_text", side_effect=OSError("Write error")):
        # 例外を発生させても関数内部で catch されるため, エラー無く終了することを確認
        apply_file_modification(str(target_file), "new_code")


def test_save_chat_history_success(tmp_path):
    """正常系: 履歴が Markdown 形式でファイルへ保存されるか検証."""
    save_file = tmp_path / "chat_history.md"
    history = ["## User\nHello", "## Model\nHi there!"]

    save_chat_history(str(save_file), history)

    assert save_file.exists()
    assert (
        save_file.read_text(encoding="utf-8") == "## User\nHello\n\n## Model\nHi there!"
    )


def test_save_chat_history_creates_parent_directory(tmp_path):
    """親ディレクトリが存在しない場合, 自動的に生成されて保存されるか検証."""
    nested_file = tmp_path / "logs" / "nested" / "history.md"
    history = ["Message 1", "Message 2"]

    save_chat_history(str(nested_file), history)

    assert nested_file.parent.exists()
    assert nested_file.exists()
    assert nested_file.read_text(encoding="utf-8") == "Message 1\n\nMessage 2"


def test_save_chat_history_exception(tmp_path):
    """異常系: ファイル書き込み時に Exception が発生した場合, except ブロックでキャッチされるか検証."""
    save_file = tmp_path / "error_history.md"
    history = ["Message 1"]

    # write_text 実行時に IOError を発生させる
    with patch.object(Path, "write_text", side_effect=OSError("Disk full")):
        # 例外が発生しても外部に送出されず, 安全に終了することを検証
        save_chat_history(str(save_file), history)


def test_handle_write_mode_confirmation_none_target_path():
    """target_path_str が None の場合, 早期リターンすること（エラーログのみ）."""
    # パス未指定時は何も実行せず終了
    handle_write_mode_confirmation(None, "```python\nprint('hello')\n```")


def test_handle_write_mode_confirmation_invalid_file(tmp_path):
    """存在しないファイルまたはディレクトリが指定された場合, 早期リターンすること."""
    non_existent = tmp_path / "non_existent.py"
    handle_write_mode_confirmation(str(non_existent), "```python\nprint('hello')\n```")


def test_handle_write_mode_confirmation_no_code_extracted(tmp_path):
    """レスポンスからコードが抽出できない場合, 早期リターンすること."""
    target_file = tmp_path / "target.py"
    target_file.write_text("print('old')", encoding="utf-8")

    # 空レスポンスを渡す
    handle_write_mode_confirmation(str(target_file), "")

    # ファイルが変更されていないこと
    assert target_file.read_text(encoding="utf-8") == "print('old')"


def test_handle_write_mode_confirmation_user_accepts(monkeypatch, tmp_path):
    """ユーザーが 'y' と入力した場合, apply_file_modification が呼び出されて上書きされるか検証."""
    target_file = tmp_path / "target.py"
    target_file.write_text("print('old')", encoding="utf-8")

    response_text = "```python\nprint('new')\n```"

    # input() の返り値を 'y' にモック
    monkeypatch.setattr("builtins.input", lambda _: "y")

    handle_write_mode_confirmation(str(target_file), response_text)

    # ファイルが上書き更新されていること
    assert target_file.read_text(encoding="utf-8") == "print('new')\n"


def test_handle_write_mode_confirmation_user_declines(monkeypatch, tmp_path):
    """ユーザーが 'n' など 'y' 以外を入力した場合, 上書きがキャンセルされるか検証."""
    target_file = tmp_path / "target.py"
    target_file.write_text("print('old')", encoding="utf-8")

    response_text = "```python\n# 既存のコード\nprint('new')\n```"

    # input() の返り値を 'n' にモック
    monkeypatch.setattr("builtins.input", lambda _: "n")

    handle_write_mode_confirmation(str(target_file), response_text)

    # ファイルが上書きされていないこと
    assert target_file.read_text(encoding="utf-8") == "print('old')"


# @patch("code_chat_cli.api.send_message_stream_with_retry")
# def test_handle_commit_msg_generation_success(mock_send_retry, capsys):
#    """git diff が存在し, Gemini API からコミットメッセージが生成されて出力されるケース."""
#    mock_client = MagicMock()
#    mock_chunk = SimpleNamespace(
#        text="feat: add commit message generation\n\n- Add -g option"
#    )
#    mock_send_retry.return_value = iter([mock_chunk])
#
#    with patch("code_chat_cli.chat.get_git_diff") as mock_get_diff:
#        mock_get_diff.return_value = "diff --git a/main.py b/main.py\n+new line"
#
#        handle_commit_generation(mock_client, "gemini-flash-latest")
#
#        mock_client.chats.create.assert_called_once_with(model="gemini-flash-latest")
#        mock_send_retry.assert_called_once()
#
#        call_kwargs = mock_send_retry.call_args.kwargs
#        assert "diff --git a/main.py b/main.py" in call_kwargs["prompt"]
#
#        captured = capsys.readouterr()
#        assert "feat: add commit message generation" in captured.out


# def test_handle_commit_msg_generation_no_diff(capsys):
#    """git diff が空の場合, API を呼び出さずにメッセージを表示して処理を抜けるケース."""
#    mock_client = MagicMock()
#
#    with patch("code_chat_cli.chat.get_git_diff") as mock_get_diff:
#        mock_get_diff.return_value = ""
#
#        handle_commit_generation(mock_client, "gemini-flash-latest")
#
#        mock_client.chats.create.assert_not_called()
#
#        captured = capsys.readouterr()
#        assert "変更（git diff）が検出されませんでした" in captured.out


# @patch("code_chat_cli.chat.get_git_diff")
# def test_handle_commit_msg_generation_called_process_error(mock_get_diff, caplog):
#    """異常系: Git コマンド実行失敗（CalledProcessError）時に例外が再送出されログが出力されるか検証."""
#    mock_client = MagicMock()
#    mock_get_diff.side_effect = subprocess.CalledProcessError(
#        returncode=1, cmd=["git", "diff"]
#    )
#
#    with pytest.raises(subprocess.CalledProcessError):
#        handle_commit_generation(mock_client, "gemini-flash-latest")
#
#    assert "Git コマンドの実行に失敗しました" in caplog.text


# @patch("code_chat_cli.api.send_message_stream_with_retry")
# @patch("code_chat_cli.chat.get_git_diff")
# def test_handle_commit_msg_generation_api_error(mock_get_diff, mock_send_retry, caplog):
#    """異常系: Gemini API エラー（APIError）発生時に例外が再送出されログが出力されるか検証."""
#    mock_client = MagicMock()
#    mock_get_diff.return_value = "diff --git a/file.py b/file.py"

#    api_error = APIError("503 Service Unavailable", {})
#    mock_send_retry.side_effect = api_error

#    with pytest.raises(APIError):
#        handle_commit_generation(mock_client, "gemini-flash-latest")

#    assert "Gemini API でエラーが発生しました" in caplog.text


# @patch("code_chat_cli.api.send_message_stream_with_retry")
# @patch("code_chat_cli.chat.get_git_diff")
# def test_handle_commit_msg_generation_unexpected_exception(
#    mock_get_diff, mock_send_retry, caplog
# ):
#    """異常系: 予期せぬ例外（Exception）発生時に例外が再送出されログが出力されるか検証."""
#    mock_client = MagicMock()
#    mock_get_diff.return_value = "diff --git a/file.py b/file.py"

# API またはストリーム呼び出し時に一般的な Exception (RuntimeError) を送出させる
#    mock_send_retry.side_effect = RuntimeError("予期せぬエラー")

#    with pytest.raises(RuntimeError):
#        handle_commit_generation(mock_client, "gemini-flash-latest")
#
#    assert "予期せぬエラーが発生しました" in caplog.text


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


def test_main_interactive_mode_exit_command(monkeypatch, mock_gemini_client):
    """対話モードで 'exit' を入力した際にメッセージ送信と正常終了が行われるか検証."""
    user_input = "こんにちは\nexit\n"
    monkeypatch.setattr("sys.stdin", io.StringIO(user_input))
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.argv", ["chat.py"])

    main()

    # chat.send_message_stream が「こんにちは」で呼び出されたか検証
    mock_gemini_client["chat"].send_message_stream.assert_called_once_with("こんにちは")


def test_main_non_interactive_pipe_mode(monkeypatch, mock_gemini_client, mock_args):
    """プロンプト指定モード時に一括処理して終了するか検証."""
    mock_args.return_value.prompt = "パイプからの入力メッセージ"

    # 対話ループに入った際に即座に EOF（終了）となるよう stdin をモック
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    monkeypatch.setattr("sys.argv", ["chat.py", "-p", "パイプからの入力メッセージ"])

    with patch("code_chat_cli.chat.time.sleep"):
        main()

    # send_message_stream が正しく呼ばれたか検証
    assert mock_gemini_client["chat"].send_message_stream.call_count == 1
    args, _ = mock_gemini_client["chat"].send_message_stream.call_args
    assert "パイプからの入力メッセージ" in args[0]


def test_main_api_error_handling(monkeypatch, mock_gemini_client):
    """API 送信時に APIError が発生した場合, sys.exit(1) で終了するか検証."""
    err = APIError.__new__(APIError)
    err.args = ("Rate limit exceeded",)
    mock_gemini_client["chat"].send_message_stream.side_effect = err

    user_input = "エラーテスト\nexit\n"
    monkeypatch.setattr("sys.stdin", io.StringIO(user_input))
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.argv", ["chat.py"])

    with patch("code_chat_cli.chat.time.sleep"), pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1


def test_main_write_mode_system_instruction(monkeypatch, mock_gemini_client, mock_args):
    """write_mode が True の場合, system_instruction に Write Mode 用の指示が追加されるか検証."""
    # write_mode を True に設定
    mock_args.return_value.write_mode = True
    mock_args.return_value.prompt = "コードを修正してください"

    # 対話ループ（while True）を 1 回で抜けるため, 2 回目の input() で EOFError を発生させる
    inputs = iter(["exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    main()

    # Client または chats.create の呼び出し引数を検証
    assert mock_gemini_client["client"].chats.create.call_count == 1
    _, kwargs = mock_gemini_client["client"].chats.create.call_args

    config = kwargs.get("config")
    system_instruction = config.system_instruction if config else ""

    # Write Mode の最重要ルールが含まれているかチェック
    assert "【厳格な遵守事項】" in system_instruction
    assert (
        "1. Markdown のコードブロック記号（```python や ```）を含めないでください."
        in system_instruction
    )
    assert (
        "2. 挨拶, 解説, 説明文, 前置き, 後書きは一切含めないでください."
        in system_instruction
    )
    assert (
        "3. 出力の1文字目から最後の文字まで, すべてPythonソースコードとして直接実行可能なテキストのみを出力してください."
        in system_instruction
    )


def test_main_with_context_no_prompt(monkeypatch, mock_gemini_client, mock_args):
    """context あり, prompt なしのルートを通過するか検証."""
    mock_args.return_value.context = "--- [ファイル内容] ---\ndef main(): pass"
    mock_args.return_value.prompt = None
    mock_args.return_value.write_mode = False

    # 初期応答をモック
    mock_response = SimpleNamespace(text="データを読み込みました.")
    mock_gemini_client["chat"].send_message.return_value = mock_response

    # 対話ループを抜けるために input で 'exit' を返す
    monkeypatch.setattr("builtins.input", lambda _: "exit")

    main()

    # chat.send_message が適切な初期メッセージで呼び出されたか検証
    mock_gemini_client["chat"].send_message_stream.assert_called_once()
    sent_prompt = mock_gemini_client["chat"].send_message_stream.call_args[0][0]

    assert "以下のソースコード・テキストを読み込んで" in sent_prompt
    assert "データを読み込みました. どのような対応を行いますか？" in sent_prompt


def test_main_with_context_and_prompt_write_mode(
    monkeypatch, mock_gemini_client, mock_args
):
    """context あり, prompt あり, write_mode=True（handle_write_mode_confirmation通過）のルートを検証."""
    mock_args.return_value.context = "--- [ファイル内容] ---\ndef main(): pass"
    mock_args.return_value.prompt = "コードをリファクタリングしてください"
    mock_args.return_value.write_mode = True
    mock_args.return_value.target_path = "src/main.py"

    # ストリーミング初期応答（チャンクのイテレータ）をモック化
    response_text = "```python\ndef main(): print('updated')\n```"
    mock_chunk = SimpleNamespace(text=response_text)
    mock_gemini_client["chat"].send_message_stream.return_value = [mock_chunk]

    # 【追加】非ストリーミング（send_message / send_message_with_retry）側の応答も設定
    mock_response = SimpleNamespace(text=response_text)
    mock_gemini_client["chat"].send_message.return_value = mock_response

    # 対話ループを即時終了
    monkeypatch.setattr("builtins.input", lambda _: "exit")

    # handle_write_mode_confirmation の実行を確認するためのモック
    with patch(
        "code_chat_cli.chat.handle_write_mode_confirmation"
    ) as mock_handle_write:
        main()

        # handle_write_mode_confirmation が指定引数で呼び出されたかを検証
        mock_handle_write.assert_called_once_with("src/main.py", response_text)

    # 送信されたプロンプト内に注記が含まれているか検証
    # （※ send_message か send_message_stream のどちらで呼ばれたかに応じて検証）
    if mock_gemini_client["chat"].send_message_stream.called:
        sent_prompt = mock_gemini_client["chat"].send_message_stream.call_args[0][0]
    else:
        sent_prompt = mock_gemini_client["chat"].send_message.call_args[0][0]

    assert "※指示に従って修正した「完全なコード全体」を省略せずに" in sent_prompt


def test_main_chat_loop_empty_input(monkeypatch, mock_gemini_client, mock_args):
    """対話ループで空文字（Enterのみ）を入力した場合, continue でループが継続されるか検証."""
    # 初期プロンプトやコンテキストがないインタラクティブモードを設定
    mock_args.return_value.context = None
    mock_args.return_value.prompt = None

    # 1回目に空文字 "", 2回目に "exit" を返すイテレータを作成
    inputs = iter(["", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    main()

    # 空文字の時は API 送信が行われないため, send_message_stream の呼び出し回数は 0 回であることを確認
    assert mock_gemini_client["chat"].send_message_stream.call_count == 0


def test_main_save_command_with_path(monkeypatch, mock_args):
    """対話ループ内で /save <filepath> を入力した場合, 指定パスへ履歴が保存されるか検証."""
    mock_args.return_value.context = None
    mock_args.return_value.prompt = None
    mock_args.return_value.output_path = None

    # 1回目に "/save custom_log.md", 2回目に "exit" を入力
    inputs = iter(["/save custom_log.md", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    with patch("code_chat_cli.chat.save_chat_history") as mock_save:
        main()

        # save_chat_history が "custom_log.md" 引数で呼び出されたことを検証
        mock_save.assert_called_once()
        assert mock_save.call_args[0][0] == "custom_log.md"


def test_main_save_command_with_default_output_path(monkeypatch, mock_args):
    """対話ループ内で引数なしの /save を入力し, output_path が設定されている場合に保存されるか検証."""
    mock_args.return_value.context = None
    mock_args.return_value.prompt = None
    mock_args.return_value.output_path = "default_output.md"

    # 1回目に "/save"（引数なし）, 2回目に "exit" を入力
    inputs = iter(["/save", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    with patch("code_chat_cli.chat.save_chat_history") as mock_save:
        main()

        # output_file ("default_output.md") を使って保存されたことを検証
        mock_save.assert_called_once()
        assert mock_save.call_args[0][0] == "default_output.md"


def test_main_save_command_no_path_specified(monkeypatch, mock_args):
    """対話ループ内で引数なしの /save を入力し, output_path も None の場合, エラーログが出力され保存されないか検証."""
    mock_args.return_value.context = None
    mock_args.return_value.prompt = None
    mock_args.return_value.output_path = None

    # 1回目に "/save"（引数なし, output_path も None）, 2回目に "exit" を入力
    inputs = iter(["/save", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    with patch("code_chat_cli.chat.save_chat_history") as mock_save:
        main()

        # save_path が None のため save_chat_history は呼ばれないことを検証
        mock_save.assert_not_called()


def test_main_chat_loop_write_mode_append_instruction(
    monkeypatch, mock_gemini_client, mock_args
):
    """対話ループ内で write_mode=True の時, 送信メッセージ末尾に指示テキストが追加されるか検証."""
    # write_mode を True に設定
    mock_args.return_value.context = None
    mock_args.return_value.prompt = None
    mock_args.return_value.write_mode = True
    mock_args.return_value.target_path = "sample.py"

    # ストリーミングレスポンスのモック化
    mock_chunk = SimpleNamespace(text="```python\nprint('hello')\n```")
    mock_gemini_client["chat"].send_message_stream.return_value = [mock_chunk]

    # 1回目にプロンプト入力, 2回目に "exit" を入力
    inputs = iter(["関数を追加してください", "exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    # handle_write_mode_confirmation の呼び出しを抑制
    with patch("code_chat_cli.chat.handle_write_mode_confirmation"):
        main()

    # chat.send_message_stream に渡された第1引数（index 0）を検証
    assert mock_gemini_client["chat"].send_message_stream.call_count == 1
    sent_prompt = mock_gemini_client["chat"].send_message_stream.call_args[0][0]

    # 送信テキスト末尾に (※指示に従って修正した... が付加されていること
    assert sent_prompt.startswith("関数を追加してください")
    assert (
        "(※指示に従って修正した「完全なコード全体」を省略せずに1つのコードブロックで出力してください)"
        in sent_prompt
    )


# @patch("code_chat_cli.args.read_stdin_content", return_value="")
# @patch("code_chat_cli.commands.commit.handle_commit_generation")
# def test_cli_generate_commit_msg_failure(mock_handle, _mock_read_stdin, monkeypatch):
#    """CLI 実行時にコミットメッセージ生成で例外が発生し, sys.exit(1) で終了することを検証."""
#    # handle_commit_generation で例外を送出させる
#    mock_handle.side_effect = RuntimeError("Unexpected Error")
#
# コマンドライン引数をシミュレート (-g フラグなどを指定)
# project_name, -g (または --generate-commit-msg) を渡す
#    monkeypatch.setattr("sys.argv", ["code-chat", "-g"])

# APIキーのチェック等で落ちないよう環境変数をダミー設定
#    monkeypatch.setenv("GEMINI_API_KEY", "dummy_key")

# sys.exit(1) が実行されると SystemExit 例外が発生する
#    with pytest.raises(SystemExit) as exc_info:
#        main()  # 引数なしで呼び出し

# 終了ステータスコードが 1 であることを検証
#    assert exc_info.value.code == 1
# 確実に呼び出されたか検証
#    mock_handle.assert_called_once()


def test_main_keyboard_interrupt(monkeypatch):
    """インタラクティブモードで KeyboardInterrupt (Ctrl+C) が発生した際, 正常終了 (exit code 0) することを発証する."""
    # parse_args と get_gemini_client をモック化
    with patch("code_chat_cli.chat.parse_args") as mock_parse_args:
        mock_args = MagicMock()
        mock_args.list_models = False
        mock_args.generate_commit_msg = False
        mock_args.debug = False
        mock_args.log_level = "INFO"
        mock_args.context = None
        mock_args.prompt = None
        mock_args.auto_save = False
        mock_args.output_path = None
        mock_parse_args.return_value = mock_args

        # input() が呼ばれたら KeyboardInterrupt を発生させる
        monkeypatch.setattr("builtins.input", MagicMock(side_effect=KeyboardInterrupt))

        # sys.exit(0) で正常終了するか検証
        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0


@pytest.mark.parametrize(
    "file_exception",
    [
        FileNotFoundError("指定されたファイルが見つかりません"),
        ValueError("無効なファイルパスです"),
        PermissionError("ファイルの読み込み権限がありません"),
    ],
)
def test_main_file_operation_exceptions(monkeypatch, mock_args, file_exception):
    """ファイル操作関連の例外 (FileNotFoundError, ValueError, PermissionError) 発生時に sys.exit(1) で終了するか検証."""
    # parse_args 呼び出し時（またはファイル操作処理時）に指定の例外を発生させる
    mock_args.side_effect = file_exception

    monkeypatch.setattr("sys.argv", ["chat.py"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    # ステータスコード 1 で終了したことを検証
    assert exc_info.value.code == 1


def test_main_unexpected_exception(monkeypatch, mock_args):
    """main() 実行中に予期せぬ例外が発生した場合, logger.critical を経由して sys.exit(1) で終了するか検証."""
    # parse_args の段階で意図的に予期せぬ例外を発生させる
    mock_args.side_effect = RuntimeError("Unexpected fatal system error")

    monkeypatch.setattr("sys.argv", ["chat.py"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    # ステータスコード 1 で終了したことを検証
    assert exc_info.value.code == 1


def test_main_finally_auto_save_enabled(monkeypatch, mock_gemini_client, mock_args):
    """auto_save=True かつ output_path 未指定の時, タイムスタンプ形式のファイル名で自動保存されるか検証."""
    mock_args.return_value.context = None
    mock_args.return_value.prompt = "こんにちは"
    mock_args.return_value.auto_save = True
    mock_args.return_value.output_path = None

    # レスポンスのモック
    mock_chunk = SimpleNamespace(text=" Gemini です.")
    mock_gemini_client["chat"].send_message_stream.return_value = [mock_chunk]

    # 対話ループをすぐに抜けるため exit を返却
    inputs = iter(["exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    with patch("code_chat_cli.chat.save_chat_history") as mock_save:
        main()

        # save_chat_history が呼び出されたか検証
        mock_save.assert_called_once()
        saved_file_path = mock_save.call_args[0][0]

        # タイムスタンプ形式 (_chat.md) のファイル名で保存されているか確認
        assert saved_file_path.endswith("_chat.md")


def test_main_finally_output_file_specified(monkeypatch, mock_gemini_client, mock_args):
    """output_path が明示的に指定されている時, 指定されたファイル名で保存されるか検証."""
    mock_args.return_value.context = None
    mock_args.return_value.prompt = "テスト"
    mock_args.return_value.auto_save = False
    mock_args.return_value.output_path = "output_result.md"

    mock_chunk = SimpleNamespace(text=" 応答です.")
    mock_gemini_client["chat"].send_message_stream.return_value = [mock_chunk]

    inputs = iter(["exit"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    with patch("code_chat_cli.chat.save_chat_history") as mock_save:
        main()

        # save_chat_history が指定した "output_result.md" で呼び出されたか検証
        mock_save.assert_called_once()
        assert mock_save.call_args[0][0] == "output_result.md"


@pytest.mark.parametrize("exception_type", [KeyboardInterrupt, EOFError])
def test_main_keyboard_interrupt_handling(
    exception_type: type[BaseException],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run_interactive_loop 実行時に KeyboardInterrupt や EOFError が発生した際,
       except ブロックを通って sys.exit(0) で正常終了することを検証する.

    Args:
        exception_type (type[BaseException]): 送出させる例外クラス.
        monkeypatch (pytest.MonkeyPatch): pytest のモックフィクスチャ.
    """
    # 最小限の引数設定
    test_args = ["chat.py"]
    monkeypatch.setattr("sys.argv", test_args)

    # CLI 引数のモック
    mock_args = MagicMock()
    mock_args.debug = False
    mock_args.log_level = "INFO"
    mock_args.write_mode = False
    mock_args.model = "gemini-flash-latest"
    mock_args.context = None
    mock_args.prompt = None
    mock_args.output_path = None
    mock_args.auto_save = False

    # 各モックの適用
    with (
        patch("code_chat_cli.chat.parse_args", return_value=mock_args),
        patch("code_chat_cli.chat._setup_cli_logging"),
        patch("code_chat_cli.chat.get_gemini_client"),
        patch("code_chat_cli.chat._handle_subcommands"),
        patch("code_chat_cli.chat._build_chat_config"),
        # run_interactive_loop が呼び出された際に指定の例外を送出させる
        patch(
            "code_chat_cli.chat.run_interactive_loop",
            side_effect=exception_type,
        ),
        patch("code_chat_cli.chat._save_history_if_needed"),
        pytest.raises(SystemExit) as exc_info,
    ):
        main()

    # sys.exit(0) で正常終了したことを検証
    assert exc_info.value.code == 0
