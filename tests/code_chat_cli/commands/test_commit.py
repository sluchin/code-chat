"""`code_chat_cli.commands.commit` モジュールのテスト."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest
from google.genai.errors import APIError

from code_chat_cli.commands.commit import handle_commit_generation


class TestHandleCommitGeneration:
    """`handle_commit_generation` のテスト."""

    def test_handle_commit_generation_success(
        self,
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

    def test_handle_commit_generation_skips_empty_text_chunk(
        self,
        mock_client: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """テキストが空 (None) のチャンクは, "None" と出力されずに読み飛ばされることを検証する."""
        chunks = [MagicMock(text="feat: x"), MagicMock(text=None)]

        with (
            patch("code_chat_cli.commands.commit.get_git_diff", return_value="diff"),
            patch(
                "code_chat_cli.commands.commit.send_message_stream_with_retry",
                return_value=chunks,
            ),
        ):
            handle_commit_generation(mock_client, "gemini-flash-latest")

        assert capsys.readouterr().out == "feat: x\n"

    def test_handle_commit_generation_called_process_error_failure(
        self,
        mock_client: MagicMock,
    ) -> None:
        """subprocess が失敗例外を送出した場合に呼び出し元へ送出されるか, 適切にキャッチされることを検証する."""
        with (
            patch(
                "subprocess.run",
                side_effect=subprocess.CalledProcessError(1, "git"),
            ),
            # 関数が例外を透過させる実装の場合は pytest.raises を使用
            pytest.raises(subprocess.CalledProcessError),
        ):
            handle_commit_generation(mock_client, "gemini-flash-latest")

    def test_handle_commit_generation_api_error_failure(
        self,
        mock_client: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Gemini API のエラーは, ここでは記録せず, そのまま呼び出し元 (chat) へ伝わるか検証する.

        エラーの概要とヒントは, 呼び出し元が 1 回だけ出力する (二重に出力しない).
        """
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
            pytest.raises(APIError),
        ):
            handle_commit_generation(mock_client, "gemini-flash-latest")

        assert not caplog.records

    def test_handle_commit_generation_unexpected_error_failure(
        self,
        mock_client: MagicMock,
    ) -> None:
        """Gemini API 以外の予期しない例外も, 握りつぶさずに呼び出し元へ伝わるか検証する."""
        with (
            patch(
                "code_chat_cli.commands.commit.get_git_diff",
                return_value="diff --git a/file.py...",
            ),
            patch(
                "code_chat_cli.commands.commit.send_message_stream_with_retry",
                side_effect=Exception("API Connection Failed"),
            ),
            pytest.raises(Exception, match="API Connection Failed"),
        ):
            handle_commit_generation(mock_client, "gemini-flash-latest")

    def test_handle_commit_generation_no_diff(
        self,
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
