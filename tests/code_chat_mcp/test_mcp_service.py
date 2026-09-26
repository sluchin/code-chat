# pylint: disable=redefined-outer-name,protected-access
"""`code_chat_mcp.mcp_service` モジュールのテスト."""

import asyncio
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from code_chat_mcp.mcp_config import McpServerConfig
from code_chat_mcp.mcp_service import McpService, McpToolInfo


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


def _fake_process(tools=None, error=None, call_result="ok"):
    process = MagicMock()
    if error:
        process.get_tools = AsyncMock(side_effect=error)
    else:
        process.get_tools = AsyncMock(return_value=tools or [])
    process.call_tool = AsyncMock(return_value=call_result)
    return process


class TestInit:
    """`McpService.__init__` のテスト."""

    def test_init_loads_servers_success(self, service, config_file):
        """初期化時に設定ファイルのサーバーが読み込まれるか検証."""
        assert service.config_path == config_file
        assert set(service.servers) == {"git", "fs"}


class TestAsyncContextManager:
    """`McpService.__aenter__ / __aexit__` のテスト."""

    def test_async_context_manager_starts_and_stops_success(self, service):
        """async with でプロセス管理オブジェクトが登録・解放されるか検証."""

        async def _run():
            async with service as svc:
                running = set(svc._processes)
            return running, dict(service._processes)

        running, after = asyncio.run(_run())

        assert running == {"git", "fs"}
        assert after == {}


class TestRun:
    """`McpService.run` のテスト."""

    def test_run_executes_tool_and_prints_success(self, service, capsys):
        """run が単発でツールを実行し, 結果を出力するか検証."""
        process = _fake_process(call_result="RESULT")

        with patch("code_chat_mcp.mcp_service.McpServerProcess", return_value=process):
            service.run("git", "status", {"x": 1})

        out = capsys.readouterr().out
        assert "=== Execution Result: status ===" in out
        assert "RESULT" in out
        process.call_tool.assert_awaited_once_with("status", {"x": 1})

    def test_run_without_arguments(self, service):
        """arguments 省略時でも実行できるか検証."""
        process = _fake_process()

        with patch("code_chat_mcp.mcp_service.McpServerProcess", return_value=process):
            service.run("git", "status")

        process.call_tool.assert_awaited_once_with("status", {})


class TestGetAllTools:
    """`McpService.get_all_tools` のテスト."""

    def test_get_all_tools_success(self, service):
        """全サーバーのツールが McpToolInfo として集約されるか検証."""
        service.servers["off"] = McpServerConfig(name="off", command="x", enabled=False)
        schema = {"type": "object"}
        process = _fake_process(tools=[_tool("status", "show", schema)])

        with patch("code_chat_mcp.mcp_service.McpServerProcess", return_value=process):
            tools = asyncio.run(service.get_all_tools())

        assert [(t.server_name, t.name) for t in tools] == [
            ("git", "status"),
            ("fs", "status"),
        ]
        assert tools[0] == McpToolInfo("git", "status", "show", schema)

    def test_get_all_tools_continues_on_error_exception(self, service, caplog):
        """あるサーバーの取得に失敗しても, 他のサーバーの処理を継続するか検証."""
        failing = _fake_process(error=RuntimeError("boom"))
        working = _fake_process(tools=[_tool("ok_tool")])

        with (
            patch(
                "code_chat_mcp.mcp_service.McpServerProcess",
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
        process = _fake_process(tools=[_tool("a", None, schema)])

        with patch("code_chat_mcp.mcp_service.McpServerProcess", return_value=process):
            tools = asyncio.run(service.get_all_tools())

        assert tools == [McpToolInfo("git", "a", None, schema)]


class TestShowStatus:
    """`McpService.show_status` のテスト."""

    def test_show_status_lists_servers_success(self, service, capsys):
        """サーバー一覧が表示され, 長いコマンドは省略されるか検証."""
        service.servers["long"] = McpServerConfig(
            name="long", command="c" * 40, enabled=False
        )

        service.show_status()

        out = capsys.readouterr().out
        assert "SERVER NAME" in out
        assert "Enabled" in out
        assert "Disabled" in out
        assert "uvx mcp-server-git" in out
        assert "c" * 27 + "..." in out

    def test_show_status_empty(self, tmp_path, capsys):
        """サーバー未登録の場合のメッセージを検証."""
        service = McpService(config_path=tmp_path / "none.json")

        service.show_status()

        assert "登録されている MCP サーバーはありません" in capsys.readouterr().out


class TestTestConnection:
    """`McpService.test_connection` のテスト."""

    def test_test_connection_success(self, service, capsys, caplog):
        """成功・失敗・無効サーバーが集計されて表示されるか検証."""
        service.servers["off"] = McpServerConfig(name="off", command="x", enabled=False)
        ok = _fake_process(tools=[_tool("t1", None), _tool("t2", "described")])
        ng = _fake_process(error=RuntimeError("down"))

        with (
            patch("code_chat_mcp.mcp_service.McpServerProcess", side_effect=[ok, ng]),
            caplog.at_level(logging.ERROR),
        ):
            asyncio.run(service.test_connection())

        out = capsys.readouterr().out
        assert "[git] Connecting... [OK] Successfully fetched 2 tools." in out
        assert "t1: No description" in out
        assert "t2: described" in out
        assert "[off] ... [SKIP] (Disabled)" in out
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
    """`McpService.start_all_servers` のテスト."""

    def test_start_all_servers_skips_disabled(self, service):
        """無効なサーバーはプロセス登録されないか検証."""
        service.servers["off"] = McpServerConfig(name="off", command="x", enabled=False)

        asyncio.run(service.start_all_servers())

        assert "off" not in service._processes
        assert set(service._processes) == {"git", "fs"}


class TestCallTool:
    """`McpService.call_tool` のテスト."""

    def test_call_tool_delegates_to_process_success(self, service):
        """起動済みサーバーのプロセスへ委譲されるか検証."""
        process = _fake_process(call_result="done")
        service._processes["git"] = process

        result = asyncio.run(service.call_tool("git", "status", {"a": 1}))

        assert result == "done"
        process.call_tool.assert_awaited_once_with("status", {"a": 1})

    def test_call_tool_requires_running_server_failure(self, service):
        """起動していないサーバーのツール呼び出しは ValueError になるか検証."""
        with pytest.raises(ValueError, match="is not running"):
            asyncio.run(service.call_tool("git", "status"))

    def test_call_tool_defaults_arguments_to_empty(self, service):
        """arguments 省略時は空辞書で呼び出されるか検証."""
        process = _fake_process()
        service._processes["git"] = process

        asyncio.run(service.call_tool("git", "status"))

        process.call_tool.assert_awaited_once_with("status", {})


class TestGetServerOrFail:
    """`McpService._get_server_or_fail` のテスト."""

    def test_get_server_or_fail_success(self, service):
        """存在するサーバーが返るか検証."""
        assert service._get_server_or_fail("git").command == "uvx"

    def test_get_server_or_fail_failure(self, service):
        """存在しないサーバーを指定した場合, 終了コード 1 で終了するか検証."""
        with pytest.raises(SystemExit) as exc_info:
            service._get_server_or_fail("unknown")

        assert exc_info.value.code == 1


class TestFormatToolsForGemini:
    """`McpService._format_tools_for_gemini` のテスト."""

    def test_format_tools_for_gemini_success(self, service):
        """ツールが server__tool 形式の関数宣言に変換されるか検証."""
        tools = [
            McpToolInfo("git", "status", "show", {"type": "object"}),
            McpToolInfo("fs", "read", None, {}),
        ]

        declarations = service._format_tools_for_gemini(tools)

        assert declarations == [
            {
                "name": "git__status",
                "description": "show",
                "parameters": {"type": "object"},
            },
            {"name": "fs__read", "description": "", "parameters": {}},
        ]
