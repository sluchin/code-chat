# pylint: disable=too-many-lines, disable=redefined-outer-name
"""`code_chat_cli.chat` モジュールのCLI引数解析, 対話セッション, エラーハンドリングのテスト."""

import io
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from code_chat_cli.chat import (
    _handle_subcommands,
    main,
    run_single_turn_mode,
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

    with patch("code_chat_cli.history.save_chat_history") as mock_save:
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
        mock_args.prompt = None
        mock_args.target_path = None
        mock_args.output_path = None
        mock_args.auto_save = False
        mock_args.generate_commit_msg = False
        mock_args.debug = False
        mock_args.log_level = "INFO"
        mock_args.list_models = False
        mock_args.context = None
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

    with patch("code_chat_cli.history.save_chat_history") as mock_save:
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

    with patch("code_chat_cli.history.save_chat_history") as mock_save:
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
        patch("code_chat_cli.history.save_history_if_needed"),
        pytest.raises(SystemExit) as exc_info,
    ):
        main()

    # sys.exit(0) で正常終了したことを検証
    assert exc_info.value.code == 0


def test_run_single_turn_mode_history_entry():
    """chat_history にコード本文ではなくメタデータ（ファイル名・サイズ）が記録されるか検証."""
    mock_chat = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "Hello response"
    mock_chat.send_message.return_value = mock_response

    cli_args = MagicMock()
    cli_args.file = "src/main.py"
    cli_args.context = "print('hello world')\n"  # 20 bytes
    cli_args.prompt = "コードをレビューしてください"
    cli_args.write_mode = True
    cli_args.output_path = None
    cli_args.interactive = False

    chat_history = []

    run_single_turn_mode(mock_chat, cli_args, chat_history)

    # chat_history[0] にファイル名とバイトサイズが含まれているか検証
    assert len(chat_history) > 0
    history_entry = chat_history[0]

    # バイト計算に合わせて 20 bytes に変更, または動的に判定
    context_bytes = len(cli_args.context.encode("utf-8"))
    expected_metadata = f"[ファイル読み込み: src/main.py ({context_bytes} bytes)]"

    assert expected_metadata in history_entry
    assert "[指示]: コードをレビューしてください" in history_entry
    # ソースコード本文自体は履歴に含まれていないことを確認
    assert "print('hello world')" not in history_entry


def test_main_generate_commit_msg_failure_exits_with_code_1():
    """-g オプション実行時にエラーが発生した場合, exit(1) で終了するか検証."""
    test_args = ["code_chat_cli", "-g"]

    with (
        patch.object(sys, "argv", test_args),
        patch("code_chat_cli.chat.parse_args") as mock_parse_args,
    ):
        mock_cli_args = MagicMock()
        mock_cli_args.generate_commit_msg = True
        mock_cli_args.list_models = False
        mock_cli_args.debug = False
        mock_parse_args.return_value = mock_cli_args

        with patch(
            "code_chat_cli.chat.handle_commit_generation",
            side_effect=RuntimeError("API Failure"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()

            assert exc_info.value.code == 1


def test_main_unexpected_exception_exc_info_logging(caplog):
    """予期せぬ例外が発生した際, debugモードの設定に応じて exc_info が切り替わるか検証."""
    test_args = ["code_chat_cli"]

    with (
        patch.object(sys, "argv", test_args),
        patch("code_chat_cli.chat.parse_args", side_effect=Exception("Fatal Boom")),
    ):
        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1
        assert "予期せぬエラーが発生しました: Fatal Boom" in caplog.text


def test_main_keyboard_interrupt_exit():
    """run_interactive_loop で KeyboardInterrupt が発生した際に sys.exit(0) されるか検証."""
    with (
        patch("code_chat_cli.chat.parse_args") as mock_args,
        patch("code_chat_cli.chat.get_gemini_client"),
        patch("code_chat_cli.chat.run_interactive_loop", side_effect=KeyboardInterrupt),
    ):
        # prompt / context が None なので run_interactive_loop に進む
        mock_args.return_value = MagicMock(
            prompt=None,
            target_path=None,
            output_path=None,
            auto_save=False,
            write_mode=False,
            debug=False,
            log_level="INFO",
            list_models=False,
            generate_commit_msg=False,
            context=None,
        )

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0


def test_main_eof_error_exit():
    """run_interactive_loop で EOFError が発生した際に sys.exit(0) されるか検証."""
    with (
        patch("code_chat_cli.chat.parse_args") as mock_args,
        patch("code_chat_cli.chat.get_gemini_client"),
        patch("code_chat_cli.chat.run_interactive_loop", side_effect=EOFError),
    ):
        mock_args.return_value = MagicMock(
            prompt=None,
            target_path=None,
            output_path=None,
            auto_save=False,
            write_mode=False,
            debug=False,
            log_level="INFO",
            list_models=False,
            generate_commit_msg=False,
            context=None,
        )

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0


@pytest.mark.parametrize("exception_type", [KeyboardInterrupt, EOFError])
def test_main_interactive_mode_exit_exceptions(
    exception_type: type[BaseException],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """input() 実行時に KeyboardInterrupt や EOFError が発生した場合、正常終了 (SystemExit: 0) することを検証する.

    Args:
        exception_type (type[BaseException]): 発生させる例外クラス (KeyboardInterrupt または EOFError).
        monkeypatch (pytest.MonkeyPatch): 環境変数やモジュール属性を事前設定するフィクスチャ.
    """
    # 最小限の引数セットを擬似設定
    test_args = ["chat.py"]
    monkeypatch.setattr("sys.argv", test_args)

    # クライアントおよび引数のモック設定 (文字列属性を明示)
    mock_client = MagicMock()
    mock_args = MagicMock()
    mock_args.debug = False
    mock_args.log_level = "INFO"
    mock_args.list_models = False
    mock_args.generate_commit_msg = False
    mock_args.review = False
    mock_args.model = "gemini-flash-latest"  # ★ 文字列を指定
    mock_args.prompt = None  # ★ None または文字列
    mock_args.context = None  # ★ None または文字列
    mock_args.output_path = None
    mock_args.auto_save = False

    # 事前処理をパスさせて確実に input() の例外に到達させる
    with (
        patch("code_chat_cli.chat.parse_args", return_value=mock_args),
        patch("code_chat_cli.chat._setup_cli_logging"),
        patch("code_chat_cli.chat.get_gemini_client", return_value=mock_client),
        patch("code_chat_cli.chat._handle_subcommands"),
        patch("builtins.input", side_effect=exception_type),
        pytest.raises(SystemExit) as exc_info,
    ):
        main()

    # sys.exit(0) で正常終了したことを検証
    assert exc_info.value.code == 0


def test_cli_generate_commit_msg_integration(
    mock_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI 経由で handle_commit_generation が適切に呼び出されることを検証する."""
    test_args = ["chat.py", "--generate-commit-msg"]
    monkeypatch.setattr("sys.argv", test_args)

    mock_args = MagicMock()
    mock_args.generate_commit_msg = True
    mock_args.review = False
    mock_args.list_models = False

    with (
        patch("code_chat_cli.chat.parse_args", return_value=mock_args),
        patch("code_chat_cli.chat.get_gemini_client", return_value=mock_client),
        # パッチ対象を commands パッケージ側に変更
        patch("code_chat_cli.chat.handle_commit_generation") as mock_handle,
        pytest.raises(SystemExit) as exc_info,
    ):
        main()

    assert exc_info.value.code == 0
    mock_handle.assert_called_once()


def test_handle_subcommands_index_success() -> None:
    """command='index' で正常終了する場合、sys.exit(0) が呼ばれること."""
    mock_client = MagicMock()
    mock_args = MagicMock(command="index", repo_path="/path/to/repo")

    with (
        patch("code_chat_cli.chat.handle_index") as mock_handle_index,
        pytest.raises(SystemExit) as exc_info,
    ):
        _handle_subcommands(mock_client, mock_args)

    mock_handle_index.assert_called_once_with("/path/to/repo")
    assert exc_info.value.code == 0


def test_handle_subcommands_index_exception() -> None:
    """command='index' 実行時に例外が発生した場合、sys.exit(1) が呼ばれること."""
    mock_client = MagicMock()
    mock_args = MagicMock(command="index", repo_path="/path/to/repo")

    with (
        patch(
            "code_chat_cli.chat.handle_index", side_effect=RuntimeError("Index failure")
        ),
        pytest.raises(SystemExit) as exc_info,
    ):
        _handle_subcommands(mock_client, mock_args)

    assert exc_info.value.code == 1


def test_handle_subcommands_ask_success() -> None:
    """command='ask' で正常終了する場合、sys.exit(0) が呼ばれること."""
    mock_client = MagicMock()
    mock_args = MagicMock(command="ask", query="how to use this?")

    with (
        patch("code_chat_cli.chat.handle_ask") as mock_handle_ask,
        pytest.raises(SystemExit) as exc_info,
    ):
        _handle_subcommands(mock_client, mock_args)

    mock_handle_ask.assert_called_once_with("how to use this?")
    assert exc_info.value.code == 0


def test_handle_subcommands_ask_exception() -> None:
    """command='ask' 実行時に例外が発生した場合、sys.exit(1) が呼ばれること."""
    mock_client = MagicMock()
    mock_args = MagicMock(command="ask", query="how to use this?")

    with (
        patch("code_chat_cli.chat.handle_ask", side_effect=RuntimeError("Ask failure")),
        pytest.raises(SystemExit) as exc_info,
    ):
        _handle_subcommands(mock_client, mock_args)

    assert exc_info.value.code == 1


def test_handle_subcommands_none() -> None:
    """サブコマンドが指定されていない場合、処理をスキップすること."""
    mock_client = MagicMock()
    mock_args = MagicMock(
        target_path=None,
        list_models=False,
        generate_commit_msg=False,
        review=False,
        command=None,
    )

    # sys.exit が呼ばれずに正常終了することを確認
    _handle_subcommands(mock_client, mock_args)
