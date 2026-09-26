# pylint: disable=redefined-outer-name,protected-access
"""`code_chat_mcp.mcp_server_process` モジュールのテスト."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import patch

import pytest
from code_chat_mcp.mcp_server_process import McpServerProcess


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
    yield


@pytest.fixture
def fake_mcp():
    """stdio_client / ClientSession を差し替える fixture."""
    FakeSession.instances = []
    with (
        patch("code_chat_mcp.mcp_server_process.stdio_client", fake_stdio_client),
        patch("code_chat_mcp.mcp_server_process.ClientSession", FakeSession),
    ):
        yield


class TestInit:
    """`McpServerProcess.__init__` のテスト."""

    def test_init_resolves_cwd_variable_success(self):
        """引数内の ${CWD} がカレントディレクトリの絶対パスに置換されるか検証."""
        process = McpServerProcess("npx", ["-y", "${CWD}/sub", "plain"], {"A": "1"})

        cwd = str(Path.cwd().resolve())
        assert process.command == "npx"
        assert process.args == ["-y", f"{cwd}/sub", "plain"]
        assert process.env == {"A": "1"}
        assert process._server_params.command == "npx"
        assert process._server_params.args == process.args

    def test_init_defaults(self):
        """引数・環境変数を省略した場合の既定値を検証."""
        process = McpServerProcess("uvx")

        assert process.args == []
        assert process.env is None


class TestConnect:
    """`McpServerProcess.connect` のテスト."""

    def test_connect_initializes_session_success(self, fake_mcp):
        """connect がセッションを初期化して返すか検証."""

        async def _run():
            async with McpServerProcess("cmd", ["a"]).connect() as session:
                return session

        session = asyncio.run(_run())

        assert session.initialized is True
        assert (session.read, session.write) == ("read-stream", "write-stream")

    def test_connect_logs_and_reraises_errors_failure(self):
        """接続中の例外がログ出力の上で再送出されるか検証."""

        async def _run():
            async with McpServerProcess("cmd").connect():
                pass

        with (
            patch(
                "code_chat_mcp.mcp_server_process.stdio_client", failing_stdio_client
            ),
            pytest.raises(RuntimeError, match="spawn failed"),
        ):
            asyncio.run(_run())


class TestGetTools:
    """`McpServerProcess.get_tools` のテスト."""

    def test_get_tools_success(self, fake_mcp):
        """get_tools がサーバーのツール一覧を返すか検証."""
        tools = asyncio.run(McpServerProcess("cmd").get_tools())

        assert [t.name for t in tools] == ["tool_a"]

    def test_get_tools_returns_empty_on_error_exception(self):
        """get_tools は接続エラー時に空リストを返すか検証."""
        with patch(
            "code_chat_mcp.mcp_server_process.stdio_client", failing_stdio_client
        ):
            tools = asyncio.run(McpServerProcess("cmd").get_tools())

        assert tools == []


class TestCallTool:
    """`McpServerProcess.call_tool` のテスト."""

    def test_call_tool_success(self, fake_mcp):
        """call_tool が引数付きでツールを実行して結果を返すか検証."""
        result = asyncio.run(McpServerProcess("cmd").call_tool("git_status", {"a": 1}))

        assert result == "result:git_status"
        assert FakeSession.instances[-1].calls == [("git_status", {"a": 1})]

    def test_call_tool_without_arguments(self, fake_mcp):
        """arguments 省略時は空辞書で呼び出されるか検証."""
        asyncio.run(McpServerProcess("cmd").call_tool("ping"))

        assert FakeSession.instances[-1].calls == [("ping", {})]


class TestResolveArgs:
    """`McpServerProcess._resolve_args` のテスト."""

    def test_resolve_args_empty(self):
        """空の引数リストはそのまま空で返るか検証."""
        assert McpServerProcess("cmd")._resolve_args([]) == []
