# pylint: disable=redefined-outer-name,protected-access
"""`code_chat_mcp.mcp_service` モジュールのテスト."""

import asyncio
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from code_chat_mcp.mcp_server_config import McpServerConfig
from code_chat_mcp.mcp_service import McpService
from code_chat_mcp.mcp_tool_info import McpToolInfo


@pytest.fixture
def config_file(tmp_path):
    """有効なサーバーを 2 つ定義した設定ファイルのパスを返す fixture."""
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "git": {"command": "uvx", "args": ["mcp-server-git"]},
                    "fs": {"command": "npx", "env": {"A": "1"}},
                }
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def service(config_file):
    """設定ファイルを読み込んだ McpService."""
    return McpService(config_path=config_file)


def _tool(name, description="desc", schema=None):
    return SimpleNamespace(name=name, description=description, inputSchema=schema or {})


def _fake_connection(tools=None, error=None, call_result="ok"):
    connection = MagicMock()
    if error:
        connection.get_tools = AsyncMock(side_effect=error)
    else:
        connection.get_tools = AsyncMock(return_value=tools or [])
    connection.call_tool = AsyncMock(return_value=call_result)
    return connection


class TestInit:
    """`McpService.__init__` のテスト."""

    def test_init_loads_servers_success(self, service, config_file):
        """初期化時に設定ファイルのサーバーが読み込まれるか検証."""
        assert service.config_path == config_file
        assert set(service.servers) == {"git", "fs"}


class TestAsyncContextManager:
    """`McpService.__aenter__ / __aexit__` のテスト."""

    def test_async_context_manager_starts_and_stops_success(self, service):
        """async with でサーバーへの接続オブジェクトが登録・解放されるか検証."""

        async def _run():
            async with service as svc:
                running = set(svc._connections)
            return running, dict(service._connections)

        running, after = asyncio.run(_run())

        assert running == {"git", "fs"}
        assert after == {}


class TestGetAllTools:
    """`McpService.get_all_tools` のテスト."""

    def test_get_all_tools_success(self, service):
        """全サーバーのツールが McpToolInfo として集約されるか検証."""
        service.servers["off"] = McpServerConfig(name="off", command="x", enabled=False)
        schema = {"type": "object"}
        connection = _fake_connection(tools=[_tool("status", "show", schema)])

        with patch(
            "code_chat_mcp.mcp_service.McpServerConnection", return_value=connection
        ):
            tools = asyncio.run(service.get_all_tools())

        assert [(t.server_name, t.name) for t in tools] == [
            ("git", "status"),
            ("fs", "status"),
        ]
        assert tools[0] == McpToolInfo("git", "status", "show", schema)

    def test_get_all_tools_continues_on_error_exception(self, service, caplog):
        """あるサーバーの取得に失敗しても, 他のサーバーの処理を継続するか検証."""
        failing = _fake_connection(error=RuntimeError("boom"))
        working = _fake_connection(tools=[_tool("ok_tool")])

        with (
            patch(
                "code_chat_mcp.mcp_service.McpServerConnection",
                side_effect=[failing, working],
            ),
            caplog.at_level(logging.ERROR),
        ):
            tools = asyncio.run(service.get_all_tools())

        assert [(t.server_name, t.name) for t in tools] == [("fs", "ok_tool")]
        assert "ツール取得に失敗しました" in caplog.text

    def test_get_all_tools_keeps_missing_description(self, service):
        """description が None のツールも, スキーマとともにそのまま保持されるか検証."""
        service.servers = {"git": service.servers["git"]}
        schema = {"type": "object", "properties": {"a": {"type": "string"}}}
        connection = _fake_connection(tools=[_tool("a", None, schema)])

        with patch(
            "code_chat_mcp.mcp_service.McpServerConnection", return_value=connection
        ):
            tools = asyncio.run(service.get_all_tools())

        assert tools == [McpToolInfo("git", "a", None, schema)]


class TestTestConnection:
    """`McpService.test_connection` のテスト."""

    def test_test_connection_success(self, service, capsys, caplog):
        """成功・失敗・無効サーバーが集計されて表示されるか検証."""
        service.servers["off"] = McpServerConfig(name="off", command="x", enabled=False)
        ok = _fake_connection(tools=[_tool("t1", None), _tool("t2", "described")])
        ng = _fake_connection(error=RuntimeError("down"))

        with (
            patch(
                "code_chat_mcp.mcp_service.McpServerConnection", side_effect=[ok, ng]
            ),
            caplog.at_level(logging.ERROR),
        ):
            asyncio.run(service.test_connection())

        out = capsys.readouterr().out
        assert "[git] Connecting... [OK] Successfully fetched 2 tools." in out
        assert "t1: No description" in out
        assert "t2: described" in out
        assert "[off] ... [SKIP] (Disabled)" in out
        assert "[NG] Failed to connect." in out
        assert "1/3 サーバーが正常に応答しました" in out
        assert "接続テスト失敗" in caplog.text

    def test_test_connection_without_servers(self, tmp_path, capsys):
        """サーバー未登録の場合は接続テストを行わないか検証."""
        service = McpService(config_path=tmp_path / "none.json")

        asyncio.run(service.test_connection())

        assert (
            "テスト対象の MCP サーバーが登録されていません" in capsys.readouterr().out
        )


class TestStartAllServers:
    """`McpService._start_all_servers` のテスト."""

    def test_start_all_servers_skips_disabled(self, service):
        """無効なサーバーは接続が登録されないか検証."""
        service.servers["off"] = McpServerConfig(name="off", command="x", enabled=False)

        asyncio.run(service._start_all_servers())

        assert "off" not in service._connections
        assert set(service._connections) == {"git", "fs"}


class TestCallTool:
    """`McpService.call_tool` のテスト."""

    def test_call_tool_delegates_to_connection_success(self, service):
        """登録済みサーバーの接続へ委譲されるか検証."""
        connection = _fake_connection(call_result="done")
        service._connections["git"] = connection

        result = asyncio.run(service.call_tool("git", "status", {"a": 1}))

        assert result == "done"
        connection.call_tool.assert_awaited_once_with("status", {"a": 1})

    def test_call_tool_requires_running_server_failure(self, service):
        """起動していないサーバーのツール呼び出しは ValueError になるか検証."""
        with pytest.raises(ValueError, match="is not running"):
            asyncio.run(service.call_tool("git", "status"))

    def test_call_tool_defaults_arguments_to_empty(self, service):
        """arguments 省略時は空辞書で呼び出されるか検証."""
        connection = _fake_connection()
        service._connections["git"] = connection

        asyncio.run(service.call_tool("git", "status"))

        connection.call_tool.assert_awaited_once_with("status", {})
