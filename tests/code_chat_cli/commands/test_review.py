# pylint: disable=redefined-outer-name
"""`code_chat_cli.commands.review` モジュールのテスト."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from code_chat_cli.commands.review import handle_code_review


@pytest.fixture
def mock_client() -> MagicMock:
    """Gemini API クライアントのモックを生成するフィクスチャ.

    Returns:
        MagicMock: ストリーミング応答をシミュレートするクライアントモック.
    """
    client = MagicMock()
    chunk1 = MagicMock()
    chunk1.text = "レビュー結果: "
    chunk2 = MagicMock()
    chunk2.text = "問題ありません."

    client.models.generate_content_stream.return_value = [chunk1, chunk2]
    return client


class TestHandleCodeReview:
    """`handle_code_review` のテスト."""

    def test_handle_code_review_single_file_success(
        self,
        mock_client: MagicMock,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """単一のテキストファイルを指定した際に正常にレビュー要求が処理されることを検証する.

        Args:
            mock_client (MagicMock): Gemini API クライアントのモック.
            tmp_path (Path): 一時ディレクトリパスを提供するフィクスチャ.
            capsys (pytest.CaptureFixture[str]): 標準出力・標準エラー出力をキャプチャするフィクスチャ.
        """
        test_file = tmp_path / "sample.py"
        test_file.write_text("print('hello world')", encoding="utf-8")

        handle_code_review(mock_client, "gemini-flash-latest", file_path=str(test_file))

        captured = capsys.readouterr()
        assert "コードレビューを実行中..." in captured.out
        assert "レビュー結果: 問題ありません." in captured.out
        mock_client.models.generate_content_stream.assert_called_once()

    def test_handle_code_review_directory_success(
        self,
        mock_client: MagicMock,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """ディレクトリ指定時に除外対象（.git等）がスキップされ, 対象ファイルのみプロンプトに含まれることを検証する.

        Args:
            mock_client (MagicMock): Gemini API クライアントのモック.
            tmp_path (Path): 一時ディレクトリパスを提供するフィクスチャ.
            capsys (pytest.CaptureFixture[str]): 標準出力・標準エラー出力をキャプチャするフィクスチャ.
        """
        # テキストファイルを配置
        (tmp_path / "main.py").write_text("def main(): pass", encoding="utf-8")
        # 無視対象ディレクトリとその中のファイル
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("git config content", encoding="utf-8")

        handle_code_review(mock_client, "gemini-flash-latest", file_path=str(tmp_path))

        captured = capsys.readouterr()
        assert "コードレビューを実行中..." in captured.out

        # 生成されたプロンプトに main.py は含まれ, .git/config は含まれないことを確認
        call_args = mock_client.models.generate_content_stream.call_args
        prompt = call_args.kwargs["contents"]
        assert "main.py" in prompt
        assert "git config content" not in prompt

    @patch("subprocess.run")
    def test_handle_code_review_git_diff_success(
        self,
        mock_subprocess: MagicMock,
        mock_client: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """git diff から変更点を取り出して正常にレビューが完了することを検証する.

        Args:
            mock_subprocess (MagicMock): subprocess.run のモック.
            mock_client (MagicMock): Gemini API クライアントのモック.
            capsys (pytest.CaptureFixture[str]): 標準出力・標準エラー出力をキャプチャするフィクスチャ.
        """
        mock_subprocess.return_value = MagicMock(
            returncode=0, stdout="--- a/file.py\n+++ b/file.py\n+import os\n"
        )

        handle_code_review(mock_client, "gemini-flash-latest", staged=True)

        # git diff --cached が呼び出されたか検証
        mock_subprocess.assert_called_once_with(
            ["git", "diff", "--cached"], capture_output=True, text=True, check=False
        )

        captured = capsys.readouterr()
        assert "レビュー結果: 問題ありません." in captured.out

    def test_handle_code_review_with_file_path_success(self, tmp_path):
        """file_path (-f) が指定された場合, read_path_content 経由でコンテンツを取得してレビューを実行すること."""
        # テスト用ファイルの作成
        test_file = tmp_path / "sample.py"
        test_file.write_text("print('hello')", encoding="utf-8")

        mock_client = MagicMock()
        mock_response = [MagicMock(text="Good code")]
        mock_client.models.generate_content_stream.return_value = mock_response

        with patch("code_chat_cli.commands.review.read_path_content") as mock_read:
            mock_read.return_value = "=== File: sample.py ===\nprint('hello')"

            handle_code_review(
                client=mock_client,
                model_name="gemini-2.5-flash",
                staged=False,
                file_path=str(test_file),
            )

            # read_path_content が呼び出されたことを検証
            mock_read.assert_called_once_with(str(test_file))
            # API が呼び出されたことを検証
            mock_client.models.generate_content_stream.assert_called_once()

    def test_handle_code_review_with_git_diff_success(self):
        """file_path が指定されない場合, _get_git_diff を使用してレビューを実行すること."""
        mock_client = MagicMock()
        mock_response = [MagicMock(text="Diff reviewed")]
        mock_client.models.generate_content_stream.return_value = mock_response

        with patch("code_chat_cli.commands.review._get_git_diff") as mock_diff:
            mock_diff.return_value = "diff --git a/file.py b/file.py"

            handle_code_review(
                client=mock_client,
                model_name="gemini-2.5-flash",
                staged=False,
                file_path=None,
            )

            mock_diff.assert_called_once_with(False)
            mock_client.models.generate_content_stream.assert_called_once()

    def test_handle_code_review_non_existent_path_failure(
        self, mock_client: MagicMock
    ) -> None:
        """存在しないファイルパスが指定された場合に標準エラー出力へ警告が出力されることを検証する.

        Args:
            mock_client (MagicMock): Gemini API クライアントのモック.
            capsys (pytest.CaptureFixture[str]): 標準出力・標準エラー出力をキャプチャするフィクスチャ.
        """
        with pytest.raises(SystemExit) as exc_info:
            handle_code_review(
                mock_client, "gemini-flash-latest", file_path="non_existent.py"
            )
        assert exc_info.value.code == 1

    def test_handle_code_review_single_file_read_exception_failure(
        self,
        mock_client: MagicMock,
        tmp_path: Path,
        # capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """単一ファイルの読み込み時に例外が発生した場合, エラーメッセージを出力して処理を中断することを検証する."""
        test_file = tmp_path / "read_error.py"
        test_file.write_text("content", encoding="utf-8")

        with (
            patch.object(
                Path, "read_text", side_effect=OSError("ファイル読み込みエラー")
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            handle_code_review(
                mock_client, "gemini-flash-latest", file_path=str(test_file)
            )

        assert exc_info.value.code == 1
        assert "読み込みに失敗しました" in caplog.text

    @patch("subprocess.run")
    def test_handle_code_review_git_diff_error_failure(
        self,
        mock_subprocess: MagicMock,
        mock_client: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """git diff の実行が非ゼロの終了ステータスで失敗した場合, エラーメッセージが出力されることを検証する."""
        mock_subprocess.return_value = MagicMock(
            returncode=128, stderr="fatal: not a git repository"
        )

        handle_code_review(mock_client, "gemini-flash-latest")

        captured = capsys.readouterr()
        assert "エラー: git diff の実行に失敗しました:" in captured.err
        assert "fatal: not a git repository" in captured.err
        mock_client.models.generate_content_stream.assert_not_called()

    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_handle_code_review_git_not_found_exception(
        self,
        mock_client: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """git コマンドが存在しない環境で例外がキャッチされ標準エラー出力にエラーが表示されることを検証する.

        Args:
            mock_client (MagicMock): Gemini API クライアントのモック.
            capsys (pytest.CaptureFixture[str]): 標準出力・標準エラー出力をキャプチャするフィクスチャ.
        """
        handle_code_review(mock_client, "gemini-flash-latest")

        captured = capsys.readouterr()
        assert "エラー: git コマンドが見つかりません." in captured.err
        mock_client.models.generate_content_stream.assert_not_called()

    def test_handle_code_review_directory_read_exception(
        self,
        mock_client: MagicMock,
        valid_and_error_files: tuple[Path, Path],
        fail_read_text,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """ディレクトリ走査中に特定ファイルの読み込み例外が発生した際, スキップログが出力され処理が継続することを検証する."""
        valid_file, _ = valid_and_error_files

        # Path.read_text の呼び出しで特定ファイルのみ例外を発生させる
        with fail_read_text("error.py", PermissionError("アクセスが拒否されました")):
            handle_code_review(
                mock_client, "gemini-flash-latest", file_path=str(valid_file.parent)
            )

        assert "読み込みをスキップしました" in caplog.text

    def test_handle_code_review_exception_handling_exception(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """generate_content_stream 実行時に例外が発生した場合の例外処理を検証."""
        mock_client = MagicMock()
        # API 呼出時に RuntimeError を発生させる設定
        mock_client.models.generate_content_stream.side_effect = RuntimeError(
            "API Error"
        )

        # git diff で何らかのコードが取得できる状況をモック
        with patch(
            "code_chat_cli.commands.review._get_git_diff",
            return_value="def foo(): pass",
        ):
            handle_code_review(client=mock_client, model_name="gemini-2.5-flash")

        # 標準エラー出力 (sys.stderr) にエラーメッセージが出力されたか確認
        captured = capsys.readouterr()
        assert "エラーが発生しました: API Error" in captured.err

    def test_handle_code_review_stream_exception_handling_exception(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """ストリームの読み込み途中で例外が発生した場合の例外処理を検証."""

        # ジェネレータの途中で例外を発生させるイテレータを模擬
        def error_stream():
            yield MagicMock(text="一部の応答")
            raise RuntimeError("Stream Error")

        mock_client = MagicMock()
        mock_client.models.generate_content_stream.return_value = error_stream()

        with patch(
            "code_chat_cli.commands.review._get_git_diff",
            return_value="def foo(): pass",
        ):
            handle_code_review(client=mock_client, model_name="gemini-2.5-flash")

        captured = capsys.readouterr()
        assert "一部の応答" in captured.out
        assert "エラーが発生しました: Stream Error" in captured.err

    @patch("subprocess.run")
    def test_handle_code_review_empty_diff(
        self,
        mock_subprocess: MagicMock,
        mock_client: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """git diff の出力が空の場合にメッセージが表示され, API呼び出しがスキップされることを検証する.

        Args:
            mock_subprocess (MagicMock): subprocess.run のモック.
            mock_client (MagicMock): Gemini API クライアントのモック.
            capsys (pytest.CaptureFixture[str]): 標準出力・標準エラー出力をキャプチャするフィクスチャ.
        """
        mock_subprocess.return_value = MagicMock(returncode=0, stdout="")

        handle_code_review(mock_client, "gemini-flash-latest")

        captured = capsys.readouterr()
        assert "レビュー対象のコードまたは変更点が見つかりませんでした." in captured.out
        mock_client.models.generate_content_stream.assert_not_called()
