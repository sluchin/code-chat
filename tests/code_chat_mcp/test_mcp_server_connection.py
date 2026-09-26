# pylint: disable=redefined-outer-name,protected-access
"""`code_chat_mcp.mcp_server_connection` モジュールのテスト."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import patch

import pytest
from code_chat_mcp.mcp_server_connection import McpServerConnection


class FakeSession:
    """mcp.ClientSession の代替."""

    instances: ClassVar[list["FakeSession"]] = []

    def __init__(self, read, write):
        self.read = read
        self.write = write
        self.initialized = False
        self.calls: list[tuple[str, dict]] = []
        FakeSession.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def initialize(self):
        self.initialized = True

    async def list_tools(self):
        return SimpleNamespace(tools=[SimpleNamespace(name="tool_a")])

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return f"result:{name}"


@asynccontextmanager
async def fake_stdio_client(_params):
    yield ("read-stream", "write-stream")


@asynccontextmanager
async def failing_stdio_client(_params):
    raise RuntimeError("spawn failed")
    yield  # pylint: disable=unreachable  # asynccontextmanager にはジェネレータが必要


@pytest.fixture
def fake_mcp():
    """stdio_client / ClientSession を差し替える fixture."""
    FakeSession.instances = []
    with (
        patch("code_chat_mcp.mcp_server_connection.stdio_client", fake_stdio_client),
        patch("code_chat_mcp.mcp_server_connection.ClientSession", FakeSession),
    ):
        yield


class TestInit:
    """`McpServerConnection.__init__` のテスト."""

    def test_init_resolves_cwd_variable_success(self):
        """引数内の ${CWD} がカレントディレクトリの絶対パスに置換されるか検証."""
        connection = McpServerConnection(
            "npx", ["-y", "${CWD}/sub", "plain"], {"A": "1"}
        )

        cwd = str(Path.cwd().resolve())
        assert connection.command == "npx"
        assert connection.args == ["-y", f"{cwd}/sub", "plain"]
        assert connection.env == {"A": "1"}
        assert connection._server_params.command == "npx"
        assert connection._server_params.args == connection.args

    def test_init_defaults(self):
        """引数・環境変数を省略した場合の既定値を検証."""
        connection = McpServerConnection("uvx")

        assert connection.args == []
        assert connection.env is None


class TestConnect:
    """`McpServerConnection.connect` のテスト."""

    @pytest.mark.usefixtures("fake_mcp")
    def test_connect_initializes_session_success(self):
        """connect がセッションを初期化して返すか検証."""

        async def _run():
            async with McpServerConnection("cmd", ["a"]).connect() as session:
                return session

        session = asyncio.run(_run())

        assert session.initialized is True
        assert (session.read, session.write) == ("read-stream", "write-stream")

    def test_connect_logs_and_reraises_errors_failure(self):
        """接続中の例外がログ出力の上で再送出されるか検証."""

        async def _run():
            async with McpServerConnection("cmd").connect():
                pass

        with (
            patch(
                "code_chat_mcp.mcp_server_connection.stdio_client", failing_stdio_client
            ),
            pytest.raises(RuntimeError, match="spawn failed"),
        ):
            asyncio.run(_run())


class TestGetTools:
    """`McpServerConnection.get_tools` のテスト."""

    @pytest.mark.usefixtures("fake_mcp")
    def test_get_tools_success(self):
        """get_tools がサーバーのツール一覧を返すか検証."""
        tools = asyncio.run(McpServerConnection("cmd").get_tools())

        assert [t.name for t in tools] == ["tool_a"]

    def test_get_tools_returns_empty_on_error_exception(self):
        """get_tools は接続エラー時に空リストを返すか検証."""
        with patch(
            "code_chat_mcp.mcp_server_connection.stdio_client", failing_stdio_client
        ):
            tools = asyncio.run(McpServerConnection("cmd").get_tools())

        assert tools == []


class TestCallTool:
    """`McpServerConnection.call_tool` のテスト."""

    @pytest.mark.usefixtures("fake_mcp")
    def test_call_tool_success(self):
        """call_tool が引数付きでツールを実行して結果を返すか検証."""
        result = asyncio.run(
            McpServerConnection("cmd").call_tool("git_status", {"a": 1})
        )

        assert result == "result:git_status"
        assert FakeSession.instances[-1].calls == [("git_status", {"a": 1})]

    @pytest.mark.usefixtures("fake_mcp")
    def test_call_tool_without_arguments(self):
        """arguments 省略時は空辞書で呼び出されるか検証."""
        asyncio.run(McpServerConnection("cmd").call_tool("ping"))

        assert FakeSession.instances[-1].calls == [("ping", {})]


class TestResolveArgs:
    """`McpServerConnection._resolve_args` のテスト."""

    def test_resolve_args_empty(self):
        """空の引数リストはそのまま空で返るか検証."""
        assert McpServerConnection("cmd")._resolve_args([]) == []
