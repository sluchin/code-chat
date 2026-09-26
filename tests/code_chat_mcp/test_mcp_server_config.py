"""`code_chat_mcp.mcp_server_config` モジュールのテスト."""

from code_chat_mcp.mcp_server_config import McpServerConfig


class TestMcpServerConfig:
    """`McpServerConfig` のテスト."""

    def test_mcp_server_config_success(self):
        """指定した値がそのまま保持されるか検証."""
        config = McpServerConfig(
            name="git",
            command="uvx",
            args=["mcp-server-git"],
            env={"A": "1"},
            enabled=False,
        )

        assert config.name == "git"
        assert config.command == "uvx"
        assert config.args == ["mcp-server-git"]
        assert config.env == {"A": "1"}
        assert config.enabled is False

    def test_mcp_server_config_defaults(self):
        """省略した項目の既定値 (空の引数・環境変数, 有効) が設定され, インスタンス間で共有されないか検証."""
        first = McpServerConfig(name="a", command="cmd")
        second = McpServerConfig(name="b", command="cmd")

        assert not first.args
        assert not first.env
        assert first.enabled is True
        first.args.append("x")
        assert not second.args
