"""引数パーサーおよびコンテキスト収集機能のテスト."""

import io
from pathlib import Path
from unittest import mock
from unittest.mock import patch

import pytest
from code_chat_cli.args import parse_args, read_path_content, read_stdin_content


@pytest.fixture(autouse=True)
def mock_stdin(monkeypatch):
    """すべてのテストで stdin をデフォルト空入力にモック."""
    monkeypatch.setattr("sys.stdin", io.StringIO(""))


def test_read_path_content_single_file(tmp_path):
    """単一ファイルが正常に読み込まれ, ヘッダーが付与された文字列が返るか検証."""
    file_path = tmp_path / "sample.py"
    file_path.write_text("print('hello')", encoding="utf-8")

    result = read_path_content(str(file_path))

    assert result == f"=== File: {file_path} ===\nprint('hello')"


def test_read_path_content_not_exists():
    """存在しないパスを指定した場合, sys.exit(1) で終了するか検証."""
    with pytest.raises(SystemExit) as exc_info:
        read_path_content("non_existent_file.txt")

    assert exc_info.value.code == 1


def test_read_path_content_file_read_error(tmp_path):
    """単一ファイルの読み込み時に例外が発生した場合, sys.exit(1) で終了するか検証."""
    file_path = tmp_path / "error_file.txt"
    file_path.write_text("content", encoding="utf-8")

    with (
        patch.object(Path, "read_text", side_effect=OSError("Permission denied")),
        pytest.raises(SystemExit) as exc_info,
    ):
        read_path_content(str(file_path))

    assert exc_info.value.code == 1


def test_read_path_content_directory_file_read_error(tmp_path):
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

    with patch("pathlib.Path.read_text", autospec=True, side_effect=custom_read_text):
        result = read_path_content(str(tmp_path))

    assert f"=== File: {valid_file} ===\nprint('ok')" in result
    assert str(error_file) not in result


def test_read_path_content_directory(tmp_path):
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


def test_read_path_content_empty_directory(tmp_path):
    """対象ファイルが存在しないディレクトリを指定した場合, 空文字列が返るか検証."""
    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir()

    result = read_path_content(str(empty_dir))

    assert result == ""


def test_read_path_content_other_path_type():
    """ファイルでもディレクトリでもない特殊なパス（ソケット等）の場合, 空文字列が返るか検証."""
    mock_path = mock.MagicMock()
    mock_path.exists.return_value = True
    mock_path.is_file.return_value = False
    mock_path.is_dir.return_value = False

    with patch("code_chat_cli.args.Path", return_value=mock_path):
        result = read_path_content("/dev/null")

    assert result == ""


def test_read_stdin_content_pipe(monkeypatch):
    """パイプ入力等の場合（isatty가 False）, 入力テキストが返るか検証."""
    monkeypatch.setattr("sys.stdin", io.StringIO("パイプからの入力内容"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    result = read_stdin_content()

    assert result == "パイプからの入力内容"


def test_read_stdin_content_tty(monkeypatch):
    """端末（tty）入力の場合（isatty True）, 空文字列が返るか検証."""
    monkeypatch.setattr("sys.stdin", io.StringIO("入力文字列"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    result = read_stdin_content()

    assert result == ""


def test_parse_args_default(monkeypatch):
    """引数を何も指定しない場合, デフォルト値（INFO）が設定されるか検証."""
    monkeypatch.setattr("sys.argv", ["chat.py"])
    args = parse_args()

    assert args.prompt == ""
    assert args.debug is False
    assert args.log_level == "INFO"
    assert args.command is None
    assert args.repo_path == "."
    assert args.query is None
    assert args.top_k == 5


def test_parse_args_prompt(monkeypatch):
    """サブコマンドなしでプロンプト文字列を指定した場合に正しく取得できるか検証."""
    monkeypatch.setattr("sys.argv", ["chat.py", "コードをレビューして"])
    args = parse_args()

    assert args.prompt == "コードをレビューして"
    assert args.command is None


def test_parse_args_debug_short_option(monkeypatch):
    """-D フラグ指定時に debug が True になるか検証."""
    monkeypatch.setattr("sys.argv", ["chat.py", "-D"])
    args = parse_args()

    assert args.debug is True


def test_parse_args_debug_long_option(monkeypatch):
    """--debug フラグ指定時に debug が True になるか検証."""
    monkeypatch.setattr("sys.argv", ["chat.py", "--debug"])
    args = parse_args()

    assert args.debug is True


def test_parse_args_log_level_custom(monkeypatch):
    """--log-level で大文字・小文字問わず正しく取得できるか検証."""
    monkeypatch.setattr("sys.argv", ["chat.py", "--log-level", "debug"])
    args = parse_args()

    assert args.log_level == "DEBUG"


def test_parse_args_invalid_log_level(monkeypatch):
    """無効な --log-level を指定した場合に SystemExit (エラー) になるか検証."""
    monkeypatch.setattr("sys.argv", ["chat.py", "--log-level", "INVALID_LEVEL"])

    with pytest.raises(SystemExit):
        parse_args()


def test_parse_args_with_stdin_context(monkeypatch):
    """標準入力（パイプ等）から入力がある場合, context に [標準入力] ヘッダー付きで格納されるか検証."""
    monkeypatch.setattr("sys.argv", ["chat.py"])

    monkeypatch.setattr("sys.stdin", io.StringIO("パイプからのテストデータ"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    args = parse_args()

    assert "--- [標準入力] ---" in args.context
    assert "パイプからのテストデータ" in args.context


def test_parse_args_with_file_context(monkeypatch, tmp_path):
    """-f / --file オプション指定時, context にファイル内容が格納されるか検証."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("ファイルの中身", encoding="utf-8")

    monkeypatch.setattr("sys.argv", ["chat.py", "-f", str(test_file)])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    args = parse_args()

    assert f"--- [パス入力: {test_file}] ---" in args.context
    assert "ファイルの中身" in args.context


def test_parse_args_rag_index_subcommand(monkeypatch):
    """index サブコマンドの指定および --repo-path の解析を検証."""
    monkeypatch.setattr("sys.argv", ["cchat", "index", "-r", "/tmp/repo"])
    args = parse_args()

    assert args.command == "index"
    assert args.repo_path == "/tmp/repo"


def test_parse_args_rag_ask_subcommand(monkeypatch):
    """ask サブコマンドの指定, query, --repo-path, --top-k の解析を検証."""
    monkeypatch.setattr(
        "sys.argv",
        ["cchat", "ask", "how to build?", "-r", "/tmp/repo", "-k", "10"],
    )
    args = parse_args()

    assert args.command == "ask"
    assert args.query == "how to build?"
    assert args.repo_path == "/tmp/repo"
    assert args.top_k == 10
