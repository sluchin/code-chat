"""`code_chat_cli.cli_args` モジュールのテスト."""

from code_chat_cli.cli_args import CliArgs


class TestCliArgs:
    """`CliArgs` のテスト."""

    def test_cli_args_success(self):
        """指定した値が保持され, 未指定の項目には既定値が設定されるか検証."""
        args = CliArgs(prompt="q", model="m", rag=True)

        assert args.prompt == "q"
        assert args.model == "m"
        assert args.rag is True
        assert args.subcommand is None
        assert args.log_level == "INFO"
        assert args.cache is False
        assert args.oauth is False
        assert args.login is False

    def test_cli_args_default_lists_are_independent(self):
        """リスト型の既定値が, インスタンス間で共有されないか検証."""
        first = CliArgs()
        second = CliArgs()

        first.files.append("a.py")

        assert not second.files
