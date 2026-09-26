"""`code_chat_mcp.mcp_tool_info` モジュールのテスト."""

from code_chat_mcp.mcp_tool_info import McpToolInfo


class TestMcpToolInfo:
    """`McpToolInfo` のテスト."""

    def test_mcp_tool_info_success(self):
        """サーバー名・ツール名・説明・入力スキーマがそのまま保持されるか検証."""
        schema = {"type": "object", "properties": {"path": {"type": "string"}}}

        info = McpToolInfo(
            server_name="fs",
            name="read",
            description="ファイルを読む",
            input_schema=schema,
        )

        assert info.server_name == "fs"
        assert info.name == "read"
        assert info.description == "ファイルを読む"
        assert info.input_schema is schema

    def test_mcp_tool_info_without_description(self):
        """説明が None でも保持できるか検証."""
        info = McpToolInfo(
            server_name="fs", name="read", description=None, input_schema={}
        )

        assert info.description is None
