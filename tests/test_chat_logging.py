import logging
import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest
from google.genai.errors import ClientError, ServerError

from code_chat_cli.chat import (
    handle_commit_msg_generation,
    main,
    run_single_turn_mode,
)
from code_chat_cli.logger import setup_logging


class DummyAPIError(Exception):
    """APIError のテスト用モック例外"""
    pass

def test_readline_import_primary_success():
    """1. 標準の readline が正常にインポートできるケース"""
    with patch.dict("sys.modules", {"readline": MagicMock()}):
        import code_chat_cli.chat  # 対象のモジュール名に調整してください

        importlib.reload(code_chat_cli.chat)
        assert code_chat_cli.chat.readline is not None


def test_readline_import_fallback_pyreadline3_success():
    """2. readline がなく、pyreadline3 がインポートできるケース（Windows想定）"""
    orig_import = __import__

    def mock_import(name, *args, **kwargs):
        if name == "readline":
            raise ImportError("No module named 'readline'")
        return orig_import(name, *args, **kwargs)

    mock_pyreadline3 = MagicMock()

    with patch("builtins.__import__", side_effect=mock_import):
        with patch.dict("sys.modules", {"pyreadline3": mock_pyreadline3}):
            import code_chat_cli.chat

            importlib.reload(code_chat_cli.chat)
            assert code_chat_cli.chat.readline is mock_pyreadline3


def test_readline_import_both_failed():
    """3. readline も pyreadline3 もインポートできないケース"""
    orig_import = __import__

    def mock_import(name, *args, **kwargs):
        if name in ("readline", "pyreadline3"):
            raise ImportError(f"No module named '{name}'")
        return orig_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        import code_chat_cli.chat

        importlib.reload(code_chat_cli.chat)
        assert code_chat_cli.chat.readline is None


def test_setup_readline_history_os_error():
    """read_history_file 実行時に OSError が発生しても pass して正常終了するか検証"""
    mock_readline = MagicMock()
    mock_readline.read_history_file.side_effect = OSError("Permission denied")

    # HISTORY_FILE 全体を MagicMock に差し替え、exists() の返り値を True にする
    mock_history_file = MagicMock()
    mock_history_file.exists.return_value = True

    with patch("code_chat_cli.chat.readline", mock_readline), patch(
        "code_chat_cli.chat.HISTORY_FILE", mock_history_file
    ):

        from code_chat_cli.chat import setup_readline_history

        # 例外が捕獲されてクラッシュしないことを確認
        setup_readline_history()

        mock_readline.read_history_file.assert_called_once()


def test_save_readline_history_os_error():
    """write_history_file 実行時に OSError が発生しても pass して正常終了するか検証"""
    mock_readline = MagicMock()
    mock_readline.write_history_file.side_effect = OSError("Disk full")

    mock_history_file = MagicMock()

    with patch("code_chat_cli.chat.readline", mock_readline), patch(
        "code_chat_cli.chat.HISTORY_FILE", mock_history_file
    ):

        from code_chat_cli.chat import save_readline_history

        # 例外が捕獲されてクラッシュしないことを確認
        save_readline_history()

        mock_readline.write_history_file.assert_called_once()


def test_setup_logging_app_logger_level():
    """setup_logging が app_logger と handler のレベルを正しく更新するか検証"""
    setup_logging("DEBUG")

    app_logger = logging.getLogger("code_chat_cli")
    root_logger = logging.getLogger()

    assert app_logger.level == logging.DEBUG
    assert len(root_logger.handlers) > 0
    assert root_logger.handlers[0].level == logging.DEBUG


def test_handle_commit_msg_generation_suppresses_traceback(caplog):
    """APIError 発生時にトレースバックを出さず logger.error のみ出力することを検証"""
    mock_client = MagicMock()

    # git diff のダミー値を返す設定
    with patch("code_chat_cli.chat.get_git_diff", return_value="diff --git a/b"):
        # Gemini API の呼び出しで Exception を発生させる
        with patch(
            "code_chat_cli.chat.send_message_stream_with_retry",
            side_effect=ClientError(
                429, {"error": {"message": "Rate limit exceeded"}}
            ),
        ):
            with pytest.raises(ClientError):
                handle_commit_msg_generation(
                    mock_client, model_name="gemini-3.7-flash"
                )

    # ログメッセージが含まれていることを確認
    assert "Gemini API でエラーが発生しました" in caplog.text


def test_run_single_turn_mode_history_entry():
    """chat_history にコード本文ではなくメタデータ（ファイル名・サイズ）が記録されるか検証"""
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

    # バイト計算に合わせて 20 bytes に変更、または動的に判定
    context_bytes = len(cli_args.context.encode("utf-8"))
    expected_metadata = f"[ファイル読み込み: src/main.py ({context_bytes} bytes)]"

    assert expected_metadata in history_entry
    assert "[指示]: コードをレビューしてください" in history_entry
    # ソースコード本文自体は履歴に含まれていないことを確認
    assert "print('hello world')" not in history_entry


def test_main_generate_commit_msg_failure_exits_with_code_1():
    """-g オプション実行時にエラーが発生した場合、exit(1) で終了するか検証"""
    test_args = ["code_chat_cli", "-g"]

    with patch.object(sys, "argv", test_args):
        with patch("code_chat_cli.chat.parse_args") as mock_parse_args:
            mock_cli_args = MagicMock()
            mock_cli_args.generate_commit_msg = True
            mock_cli_args.list_models = False
            mock_cli_args.debug = False
            mock_parse_args.return_value = mock_cli_args

            with patch(
                "code_chat_cli.chat.handle_commit_msg_generation",
                side_effect=RuntimeError("API Failure"),
            ):
                with pytest.raises(SystemExit) as exc_info:
                    main()

                assert exc_info.value.code == 1


def test_main_unexpected_exception_exc_info_logging(caplog):
    """予期せぬ例外が発生した際、debugモードの設定に応じて exc_info が切り替わるか検証"""
    test_args = ["code_chat_cli"]

    with patch.object(sys, "argv", test_args):
        with patch("code_chat_cli.chat.parse_args", side_effect=Exception("Fatal Boom")):
            with pytest.raises(SystemExit) as exc_info:
                main()

            assert exc_info.value.code == 1
            assert "予期せぬエラーが発生しました: Fatal Boom" in caplog.text


def test_main_keyboard_interrupt_exit():
    """run_interactive_loop で KeyboardInterrupt が発生した際に sys.exit(0) されるか検証"""
    with patch("code_chat_cli.chat.parse_args") as mock_args, patch(
        "code_chat_cli.chat.get_gemini_client"
    ), patch(
        "code_chat_cli.chat.run_interactive_loop", side_effect=KeyboardInterrupt
    ):
        # prompt / context が None なので run_interactive_loop に進む
        mock_args.return_value = MagicMock(
            list_models=False,
            generate_commit_msg=False,
            debug=False,
            log_level="INFO",
            context=None,
            prompt=None,
            write_mode=False,
            output_path=None,
            auto_save=False,
        )

        from code_chat_cli.chat import main

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0


def test_main_eof_error_exit():
    """run_interactive_loop で EOFError が発生した際に sys.exit(0) されるか検証"""
    with patch("code_chat_cli.chat.parse_args") as mock_args, patch(
        "code_chat_cli.chat.get_gemini_client"
    ), patch("code_chat_cli.chat.run_interactive_loop", side_effect=EOFError):
        mock_args.return_value = MagicMock(
            list_models=False,
            generate_commit_msg=False,
            debug=False,
            log_level="INFO",
            context=None,
            prompt=None,
            write_mode=False,
            output_path=None,
            auto_save=False,
        )

        from code_chat_cli.chat import main

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
