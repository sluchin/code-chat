"""コミットメッセージ自動生成機能のテスト."""

import logging
import subprocess
from unittest.mock import MagicMock, patch
import pytest

from google.genai.errors import APIError

from code_chat_cli.commands.commit import handle_commit_generation


def test_handle_commit_msg_generation_success(
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """git diff が存在する場合に正常にコミットメッセージが生成されることを検証する."""
    # ストリーミング出力用のチャンクをモック
    mock_chunk = MagicMock()
    mock_chunk.text = "feat: add commit generation feature"

    with (
        # git diff 取得処理をモック化 (commands/commit.py 内でインポートしているパスを指定)
        patch(
            "code_chat_cli.commands.commit.get_git_diff",
            return_value="diff --git a/file.py...",
        ),
        # ストリーミング API 呼び出し関数をモック化
        patch(
            "code_chat_cli.commands.commit.send_message_stream_with_retry",
            return_value=[mock_chunk],
        ) as mock_send,
    ):
        handle_commit_generation(mock_client, "gemini-flash-latest")

        captured = capsys.readouterr()
        
        # 検証
        assert "feat: add commit generation feature" in captured.out
        mock_send.assert_called_once()


def test_handle_commit_msg_generation_no_diff(
    mock_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """git diff が空の場合に生成処理がスキップされることを検証する."""
    with patch("subprocess.run") as mock_run:
        # ステージング・ワークツリーともに diff なし
        mock_run.return_value = MagicMock(returncode=0, stdout="")

        handle_commit_generation(mock_client, "gemini-flash-latest")

        captured = capsys.readouterr()
        # 修正: プロダクトコードの出力文字列に合わせる
        assert "変更（git diff）が検出されませんでした" in captured.out
        mock_client.models.generate_content.assert_not_called()


def test_handle_commit_msg_generation_called_process_error(
    mock_client: MagicMock,
) -> None:
    """subprocess が失敗例外を送出した場合に呼び出し元へ送出されるか、適切にキャッチされることを検証する."""
    with patch(
        "subprocess.run",
        side_effect=subprocess.CalledProcessError(1, "git"),
    ):
        # 関数が例外を透過させる実装の場合は pytest.raises を使用
        with pytest.raises(subprocess.CalledProcessError):
            handle_commit_generation(mock_client, "gemini-flash-latest")


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
        from code_chat_cli.chat import main

        main()

    assert exc_info.value.code == 0
    mock_handle.assert_called_once()


def test_handle_commit_msg_generation_suppresses_traceback(
    mock_client: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """API例外発生時に例外が呼び出し元へ伝播し、ログにエラーメッセージが出力されることを検証する."""
    with (
        patch(
            "code_chat_cli.commands.commit.get_git_diff",
            return_value="diff --git a/file.py...",
        ),
        patch(
            "code_chat_cli.commands.commit.send_message_stream_with_retry",
            side_effect=Exception("API Connection Failed"),
        ),
    ):
        # 発生した Exception をキャッチする
        with pytest.raises(Exception, match="API Connection Failed"):
            handle_commit_generation(mock_client, "gemini-flash-latest")

    # logging モジュールで出力されたログメッセージの検証
    assert "API Connection Failed" in caplog.text


def test_handle_commit_generation_api_error_non_debug(
    mock_client: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """非 DEBUG モード時に APIError が発生した場合、型名がログに出力され再送出されることを検証する."""
    # False ルート (logger.isEnabledFor(logging.DEBUG) == False)
    caplog.set_level(logging.INFO)

    # google-genai の APIError などの例外インスタンスを作成
    api_error = APIError(400, {"error": {"message": "Bad Request"}})

    with (
        patch(
            "code_chat_cli.commands.commit.get_git_diff",
            return_value="diff --git a/file.py...",
        ),
        patch(
            "code_chat_cli.commands.commit.send_message_stream_with_retry",
            side_effect=api_error,
        ),
    ):
        with pytest.raises(APIError):
            handle_commit_generation(mock_client, "gemini-flash-latest")

    # ログに型名 (APIError) が含まれているか検証
    assert "Gemini API でエラーが発生しました: APIError" in caplog.text


def test_handle_commit_generation_api_error_non_debug(
    mock_client: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """非 DEBUG モード時に APIError が発生した場合、型名がログに出力され再送出されることを検証する."""
    # 対象ロガーのログレベルを INFO に設定して logger.isEnabledFor(logging.DEBUG) を False にする
    caplog.set_level(logging.INFO, logger="code_chat_cli.commands.commit")

    api_error = APIError(400, {"error": {"message": "Bad Request"}})

    with (
        patch(
            "code_chat_cli.commands.commit.get_git_diff",
            return_value="diff --git a/file.py...",
        ),
        patch(
            "code_chat_cli.commands.commit.send_message_stream_with_retry",
            side_effect=api_error,
        ),
    ):
        with pytest.raises(APIError):
            handle_commit_generation(mock_client, "gemini-flash-latest")

    # False ルートが通り、型名 (APIError) がログに含まれることを検証
    assert "Gemini API でエラーが発生しました: APIError" in caplog.text


def test_handle_commit_generation_api_error_debug(
    mock_client: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """DEBUG モード時に APIError が発生した場合、エラーの詳細文字列がログに出力され再送出されることを検証する."""
    # 対象ロガーのログレベルを DEBUG に設定して logger.isEnabledFor(logging.DEBUG) を True にする
    caplog.set_level(logging.DEBUG, logger="code_chat_cli.commands.commit")

    error_message = "Detailed API Error Message"
    api_error = APIError(500, {"error": {"message": error_message}})

    with (
        patch(
            "code_chat_cli.commands.commit.get_git_diff",
            return_value="diff --git a/file.py...",
        ),
        patch(
            "code_chat_cli.commands.commit.send_message_stream_with_retry",
            side_effect=api_error,
        ),
    ):
        with pytest.raises(APIError):
            handle_commit_generation(mock_client, "gemini-flash-latest")

    # True ルートが通り、詳細文字列 (str(e)) がログに含まれることを検証
    assert error_message in caplog.text
