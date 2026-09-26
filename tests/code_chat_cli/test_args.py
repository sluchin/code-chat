"""引数パーサーおよびコンテキスト収集機能のテスト."""

import io
from unittest.mock import patch

import pytest

from code_chat_cli.args import _read_stdin_content, parse_args


@pytest.fixture(autouse=True)
def mock_stdin(monkeypatch):
    """すべてのテストで stdin をデフォルト空入力にモック."""
    monkeypatch.setattr("sys.stdin", io.StringIO(""))


class TestParseArgs:
    """`parse_args` のテスト."""

    def test_parse_args_default_success(self, monkeypatch):
        """引数を何も指定しない場合, デフォルト値（INFO）が設定されるか検証."""
        monkeypatch.setattr("sys.argv", ["chat.py"])
        args = parse_args()

        assert args.prompt == ""
        assert args.debug_mode is False
        assert args.log_level == "INFO"
        assert args.subcommand is None
        assert args.output_dir == "./.chroma_db"

    def test_parse_args_prompt_success(self, monkeypatch):
        """サブコマンドなしでプロンプト文字列を指定した場合に正しく取得できるか検証."""
        monkeypatch.setattr("sys.argv", ["chat.py", "コードをレビューして"])
        args = parse_args()

        assert args.prompt == "コードをレビューして"
        assert args.subcommand is None

    def test_parse_args_debug_short_option_success(self, monkeypatch):
        """-D フラグ指定時に debug が True になるか検証."""
        monkeypatch.setattr("sys.argv", ["chat.py", "-D"])
        args = parse_args()

        assert args.debug_mode is True

    def test_parse_args_debug_long_option_success(self, monkeypatch):
        """--debug フラグ指定時に debug が True になるか検証."""
        monkeypatch.setattr("sys.argv", ["chat.py", "--debug"])
        args = parse_args()

        assert args.debug_mode is True

    def test_parse_args_log_level_custom_success(self, monkeypatch):
        """--log-level で大文字・小文字問わず正しく取得できるか検証."""
        monkeypatch.setattr("sys.argv", ["chat.py", "--log-level", "debug"])
        args = parse_args()

        assert args.log_level == "DEBUG"

    def test_parse_args_with_stdin_context_success(self, monkeypatch):
        """標準入力（パイプ等）から入力がある場合, context に [標準入力] ヘッダー付きで格納されるか検証."""
        monkeypatch.setattr("sys.argv", ["chat.py"])

        monkeypatch.setattr("sys.stdin", io.StringIO("パイプからのテストデータ"))
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)

        args = parse_args()

        assert "--- [標準入力] ---" in args.context
        assert "パイプからのテストデータ" in args.context

    @pytest.mark.parametrize(
        "argv",
        [
            ["rag", "status"],
            ["cache", "list"],
            ["mcp", "status"],
            ["--list-models"],
            ["--login"],
            ["--generate-commit-msg"],
            ["--review"],
        ],
    )
    def test_parse_args_does_not_read_stdin_for_commands_without_context(
        self, monkeypatch, argv
    ):
        """コンテキストを使わないコマンドでは, 標準入力を読み込まない (入力の終了を待って固まらない) か検証."""
        monkeypatch.setattr("sys.argv", ["chat.py", *argv])
        monkeypatch.setattr("sys.stdin", io.StringIO("パイプからのテストデータ"))
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)

        args = parse_args()

        assert not args.context

    def test_parse_args_with_file_context_success(self, monkeypatch, tmp_path):
        """-f / --file オプション指定時, context にファイル内容が格納されるか検証."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("ファイルの中身", encoding="utf-8")

        monkeypatch.setattr("sys.argv", ["chat.py", "-f", str(test_file)])
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)

        args = parse_args()

        assert f"--- [パス入力: {test_file}] ---" in args.context
        assert "ファイルの中身" in args.context

    def test_parse_args_rag_create_subcommand_success(self, monkeypatch):
        """rag create サブコマンドと --input_dirs の複数指定, --output_dir の解析を検証."""
        monkeypatch.setattr(
            "sys.argv",
            [
                "cchat",
                "rag",
                "create",
                "--input_dirs",
                "/tmp/a",
                "/tmp/b",
                "--output_dir",
                "/tmp/db",
            ],
        )
        args = parse_args()

        assert args.subcommand == "rag"
        assert args.subcommand_action == "create"
        assert args.input_dirs == ["/tmp/a", "/tmp/b"]
        assert args.output_dir == "/tmp/db"

    def test_parse_args_rag_update_single_input_dir_success(self, monkeypatch):
        """--input_dirs に 1 つのパスを渡しても文字単位に分解されないことを検証."""
        monkeypatch.setattr(
            "sys.argv", ["cchat", "rag", "update", "--input_dirs", "src"]
        )
        args = parse_args()

        assert args.subcommand_action == "update"
        assert args.input_dirs == ["src"]

    def test_parse_args_prompt_with_options_success(self, monkeypatch):
        """位置引数のプロンプトがオプションと混在しても, サブコマンドとして誤認されないことを検証."""
        monkeypatch.setattr(
            "sys.argv", ["chat.py", "hello", "world", "-m", "gemini-x", "-f", "a.py"]
        )
        with patch(
            "code_chat_cli.args.read_path_content",
            return_value="content",
        ):
            args = parse_args()

        assert args.prompt == "hello world"
        assert args.model == "gemini-x"
        assert args.files == ["a.py"]
        assert args.subcommand is None

    def test_parse_args_review_staged_success(self, monkeypatch):
        """--review と --staged が解析されるか検証."""
        monkeypatch.setattr("sys.argv", ["chat.py", "--review", "--staged"])
        args = parse_args()

        assert args.review is True
        assert args.staged is True

    def test_parse_args_login_success(self, monkeypatch):
        """--login が解析されるか検証."""
        monkeypatch.setattr("sys.argv", ["chat.py", "--login"])
        args = parse_args()

        assert args.login is True
        assert args.oauth is False

    def test_parse_args_oauth_success(self, monkeypatch):
        """--oauth が解析されるか検証."""
        monkeypatch.setattr("sys.argv", ["chat.py", "--oauth", "こんにちは"])
        args = parse_args()

        assert args.oauth is True
        assert args.login is False

    def test_parse_args_cache_success(self, monkeypatch):
        """-c が最新キャッシュの自動選択, --cache=<ID> が特定キャッシュの指定として解析され, プロンプトは維持されるか検証."""
        monkeypatch.setattr("sys.argv", ["chat.py", "-c", "質問です"])
        latest = parse_args()
        monkeypatch.setattr(
            "sys.argv", ["chat.py", "--cache=cachedContents/abc", "質問です"]
        )
        specified = parse_args()

        assert latest.cache is True
        assert latest.prompt == "質問です"
        assert specified.cache == "cachedContents/abc"
        assert specified.prompt == "質問です"

    def test_parse_args_cache_with_mcp_success(self, monkeypatch):
        """-c と --mcp の併用は, 引数のエラーにならないか検証 (併用の可否は, Gemini API が判断する)."""
        monkeypatch.setattr("sys.argv", ["chat.py", "-c", "--mcp", "質問です"])

        args = parse_args()

        assert args.cache is True
        assert args.mcp is True

    def test_parse_args_provider_success(self, monkeypatch):
        """--provider は, 既定が gemini で, gemini を明示しても受け付けるか検証."""
        monkeypatch.setattr("sys.argv", ["chat.py", "質問です"])
        default = parse_args()
        monkeypatch.setattr("sys.argv", ["chat.py", "-p", "gemini", "質問です"])
        specified = parse_args()

        assert default.provider == "gemini"
        assert specified.provider == "gemini"
        assert specified.prompt == "質問です"

    def test_parse_args_provider_unsupported_failure(self, monkeypatch, capsys):
        """未実装のプロバイダを指定すると, 黙って無視されずに, 引数のエラーになるか検証."""
        monkeypatch.setattr("sys.argv", ["chat.py", "-p", "openai", "質問です"])

        with pytest.raises(SystemExit) as exc_info:
            parse_args()

        assert exc_info.value.code == 2
        assert "invalid choice" in capsys.readouterr().err

    def test_parse_args_max_tool_rounds_success(self, monkeypatch):
        """--max-tool-rounds は, 既定が 20 で, 指定した値が反映され, 値がプロンプトにならないか検証."""
        monkeypatch.setattr("sys.argv", ["chat.py", "質問です"])
        default = parse_args()
        monkeypatch.setattr(
            "sys.argv", ["chat.py", "--mcp", "--max-tool-rounds", "5", "質問です"]
        )
        specified = parse_args()

        assert default.max_tool_rounds == 20
        assert specified.max_tool_rounds == 5
        assert specified.prompt == "質問です"

    @pytest.mark.parametrize("value", ["0", "-1", "abc"])
    def test_parse_args_max_tool_rounds_failure(self, monkeypatch, capsys, value):
        """--max-tool-rounds に 1 以上の整数以外を指定すると, 引数のエラーになるか検証."""
        monkeypatch.setattr("sys.argv", ["chat.py", f"--max-tool-rounds={value}", "q"])

        with pytest.raises(SystemExit) as exc_info:
            parse_args()

        assert exc_info.value.code == 2
        assert "1 以上の整数を指定してください" in capsys.readouterr().err

    def test_parse_args_cache_subcommand_success(self, monkeypatch):
        """cache create の対象パスと --ttl が解析されるか検証."""
        monkeypatch.setattr(
            "sys.argv", ["chat.py", "cache", "create", "src", "--ttl", "120"]
        )
        args = parse_args()

        assert args.subcommand == "cache"
        assert args.subcommand_action == "create"
        assert args.subcommand_target == "src"
        assert args.cache_ttl == 120

    def test_parse_args_cache_update_ttl_success(self, monkeypatch):
        """cache update の --ttl が解析され, 省略時は 3600 秒になるか検証."""
        monkeypatch.setattr("sys.argv", ["chat.py", "cache", "update", "src"])
        default = parse_args()
        monkeypatch.setattr(
            "sys.argv", ["chat.py", "cache", "update", "src", "--ttl", "120"]
        )
        specified = parse_args()

        assert default.cache_ttl == 3600
        assert specified.cache_ttl == 120

    @pytest.mark.parametrize("option", ["--rag", "--mcp"])
    def test_parse_args_file_with_rag_or_mcp_failure(
        self, monkeypatch, tmp_path, capsys, option
    ):
        """-f と --rag / --mcp を同時に指定した場合に, エラー (終了コード 2) で終了するか検証."""
        target = tmp_path / "a.py"
        target.write_text("print('a')", encoding="utf-8")
        monkeypatch.setattr("sys.argv", ["chat.py", option, "-f", str(target), "q"])

        with pytest.raises(SystemExit) as exc_info:
            parse_args()

        assert exc_info.value.code == 2
        assert "-f/--file は --rag / --mcp と併用できません" in capsys.readouterr().err

    @pytest.mark.parametrize(
        ("argv", "message"),
        [
            (["-c", "-w", "q"], "-c/--cache は -w/--write と併用できません"),
            (["-c", "--oauth", "q"], "--oauth と併用できません"),
            (["cache", "list", "--oauth"], "--oauth と併用できません"),
        ],
    )
    def test_parse_args_cache_conflict_failure(
        self, monkeypatch, capsys, argv, message
    ):
        """Context Caching が --mcp / -w / --oauth と併用された場合に, エラー (終了コード 2) で終了するか検証."""
        monkeypatch.setattr("sys.argv", ["chat.py", *argv])

        with pytest.raises(SystemExit) as exc_info:
            parse_args()

        assert exc_info.value.code == 2
        assert message in capsys.readouterr().err

    def test_parse_args_invalid_log_level_failure(self, monkeypatch):
        """無効な --log-level を指定した場合に SystemExit (エラー) になるか検証."""
        monkeypatch.setattr("sys.argv", ["chat.py", "--log-level", "INVALID_LEVEL"])

        with pytest.raises(SystemExit):
            parse_args()


class TestReadStdinContent:
    """`_read_stdin_content` のテスト."""

    def test_read_stdin_content_pipe_success(self, monkeypatch):
        """パイプ入力等の場合（isatty가 False）, 入力テキストが返るか検証."""
        monkeypatch.setattr("sys.stdin", io.StringIO("パイプからの入力内容"))
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)

        result = _read_stdin_content()

        assert result == "パイプからの入力内容"

    def test_read_stdin_content_tty(self, monkeypatch):
        """端末（tty）入力の場合（isatty True）, 空文字列が返るか検証."""
        monkeypatch.setattr("sys.stdin", io.StringIO("入力文字列"))
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)

        result = _read_stdin_content()

        assert result == ""
