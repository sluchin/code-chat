"""`code_chat_cli.file_utils` モジュールのテスト."""

from pathlib import Path
from unittest import mock
from unittest.mock import patch

import pytest
from code_chat_cli.file_utils import read_path_content


class TestReadPathContent:
    """`read_path_content` のテスト."""

    def test_read_path_content_single_file_success(self, tmp_path):
        """単一ファイルが正常に読み込まれ, ヘッダーが付与された文字列が返るか検証."""
        file_path = tmp_path / "sample.py"
        file_path.write_text("print('hello')", encoding="utf-8")

        result = read_path_content(str(file_path))

        assert result == f"=== File: {file_path} ===\nprint('hello')"

    def test_read_path_content_directory_success(self, tmp_path):
        """ディレクトリ指定時, 対象拡張子のみ読み込まれ除外対象ディレクトリがスキップされるか検証."""
        valid_file1 = tmp_path / "valid.py"
        valid_file1.write_text("code", encoding="utf-8")

        sub_dir = tmp_path / "sub"
        sub_dir.mkdir()
        valid_file2 = sub_dir / "valid.md"
        valid_file2.write_text("markdown", encoding="utf-8")

        ignored_file = tmp_path / "ignored.exe"
        ignored_file.write_text("binary", encoding="utf-8")

        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        hidden_file = git_dir / "hidden.py"
        hidden_file.write_text("git_code", encoding="utf-8")

        result = read_path_content(str(tmp_path))

        assert f"=== File: {valid_file1} ===\ncode" in result
        assert f"=== File: {valid_file2} ===\nmarkdown" in result

        assert str(ignored_file) not in result
        assert str(hidden_file) not in result

    def test_read_path_content_not_exists_failure(self):
        """存在しないパスを指定した場合, sys.exit(1) で終了するか検証."""
        with pytest.raises(SystemExit) as exc_info:
            read_path_content("non_existent_file.txt")

        assert exc_info.value.code == 1

    def test_read_path_content_file_read_error_failure(self, tmp_path):
        """単一ファイルの読み込み時に例外が発生した場合, sys.exit(1) で終了するか検証."""
        file_path = tmp_path / "error_file.txt"
        file_path.write_text("content", encoding="utf-8")

        with (
            patch.object(Path, "read_text", side_effect=OSError("Permission denied")),
            pytest.raises(SystemExit) as exc_info,
        ):
            read_path_content(str(file_path))

        assert exc_info.value.code == 1

    def test_read_path_content_directory_file_read_error_exception(self, tmp_path):
        """ディレクトリ内の特定ファイル読み込み時に例外が発生した場合, ログを出力してそのファイルをスキップするか検証."""
        valid_file = tmp_path / "valid.py"
        valid_file.write_text("print('ok')", encoding="utf-8")

        error_file = tmp_path / "error.py"
        error_file.write_text("print('error')", encoding="utf-8")

        original_read_text = Path.read_text

        def custom_read_text(path_obj, *args, **kwargs):
            if path_obj.name == "error.py":
                raise OSError("Read failure test")
            return original_read_text(path_obj, *args, **kwargs)

        with patch(
            "pathlib.Path.read_text", autospec=True, side_effect=custom_read_text
        ):
            result = read_path_content(str(tmp_path))

        assert f"=== File: {valid_file} ===\nprint('ok')" in result
        assert str(error_file) not in result

    def test_read_path_content_empty_directory(self, tmp_path):
        """対象ファイルが存在しないディレクトリを指定した場合, 空文字列が返るか検証."""
        empty_dir = tmp_path / "empty_dir"
        empty_dir.mkdir()

        result = read_path_content(str(empty_dir))

        assert result == ""

    def test_read_path_content_other_path_type(self):
        """ファイルでもディレクトリでもない特殊なパス（ソケット等）の場合, 空文字列が返るか検証."""
        mock_path = mock.MagicMock()
        mock_path.exists.return_value = True
        mock_path.is_file.return_value = False
        mock_path.is_dir.return_value = False

        with patch("code_chat_cli.file_utils.Path", return_value=mock_path):
            result = read_path_content("/dev/null")

        assert result == ""
