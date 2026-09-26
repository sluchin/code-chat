"""`code_chat_cli.mcp` モジュールのテスト."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.genai.errors import APIError

from code_chat_cli.mcp import handle_mcp_run, handle_mcp_status, handle_mcp_test
from code_chat_mcp.mcp_tool_info import McpToolInfo


def _service_cm(service: MagicMock) -> MagicMock:
    """async with で service を返す McpService クラスのモックを作成する."""
    service_cls = MagicMock()
    service_cls.return_value.__aenter__ = AsyncMock(return_value=service)
    service_cls.return_value.__aexit__ = AsyncMock(return_value=False)
    return service_cls


class TestHandleMcpRun:
    """`handle_mcp_run` のテスト."""

    def test_handle_mcp_run_returns_handler_result_success(self):
        """handle_mcp_run が QueryHandler の結果を返し, 設定パスを渡すか検証."""
        service_cls = _service_cm(MagicMock())
        handler = MagicMock()
        handler.run = AsyncMock(return_value="final answer")

        with (
            patch("code_chat_cli.mcp.McpService", service_cls),
            patch("code_chat_cli.mcp.get_gemini_client") as client_cls,
            patch(
                "code_chat_cli.mcp.QueryHandler", return_value=handler
            ) as handler_cls,
        ):
            result = asyncio.run(handle_mcp_run("hello", config_path="conf.json"))

        assert result == "final answer"
        service_cls.assert_called_once_with(config_path=Path("conf.json"))
        handler_cls.assert_called_once()
        assert handler_cls.call_args.kwargs["gemini_client"] is client_cls.return_value
        handler.run.assert_awaited_once_with("hello")

    def test_handle_mcp_run_model_and_cache_success(self):
        """モデルとキャッシュ名が, QueryHandler に渡されるか検証."""
        service_cls = _service_cm(MagicMock())
        handler = MagicMock()
        handler.run = AsyncMock(return_value="answer")

        with (
            patch("code_chat_cli.mcp.McpService", service_cls),
            patch("code_chat_cli.mcp.get_gemini_client"),
            patch(
                "code_chat_cli.mcp.QueryHandler", return_value=handler
            ) as handler_cls,
        ):
            asyncio.run(
                handle_mcp_run(
                    "hello",
                    model_name="models/gemini-cache",
                    cached_content="cachedContents/abc",
                )
            )

        assert handler_cls.call_args.kwargs["model_name"] == "models/gemini-cache"
        assert handler_cls.call_args.kwargs["cached_content"] == "cachedContents/abc"

    def test_handle_mcp_run_max_tool_rounds_success(self):
        """ツール呼び出しの回数の上限が, 指定した値 (省略時は既定値) で QueryHandler に渡されるか検証."""
        service_cls = _service_cm(MagicMock())
        handler = MagicMock()
        handler.run = AsyncMock(return_value="answer")

        with (
            patch("code_chat_cli.mcp.McpService", service_cls),
            patch("code_chat_cli.mcp.get_gemini_client"),
            patch(
                "code_chat_cli.mcp.QueryHandler", return_value=handler
            ) as handler_cls,
        ):
            asyncio.run(handle_mcp_run("hello"))
            asyncio.run(handle_mcp_run("hello", max_tool_rounds=3))

        rounds = [c.kwargs["max_tool_rounds"] for c in handler_cls.call_args_list]
        assert rounds == [20, 3]

    def test_handle_mcp_run_use_oauth_success(self):
        """use_oauth が Gemini クライアントの作成に渡されるか検証."""
        service_cls = _service_cm(MagicMock())
        handler = MagicMock()
        handler.run = AsyncMock(return_value="answer")

        with (
            patch("code_chat_cli.mcp.McpService", service_cls),
            patch("code_chat_cli.mcp.get_gemini_client") as get_client,
            patch("code_chat_cli.mcp.QueryHandler", return_value=handler),
        ):
            asyncio.run(handle_mcp_run("hello", use_oauth=True))

        get_client.assert_called_once_with(use_oauth=True)

    def test_handle_mcp_run_reraises_errors_failure(self, caplog):
        """処理中の例外がログ出力の上で再送出されるか検証."""
        service_cls = _service_cm(MagicMock())
        handler = MagicMock()
        handler.run = AsyncMock(side_effect=RuntimeError("boom"))

        with (
            patch("code_chat_cli.mcp.McpService", service_cls),
            patch("code_chat_cli.mcp.get_gemini_client"),
            patch("code_chat_cli.mcp.QueryHandler", return_value=handler),
            pytest.raises(RuntimeError, match="boom"),
        ):
            asyncio.run(handle_mcp_run("hello"))

        assert "handle_mcp_run 実行中にエラーが発生しました" in caplog.text

    def test_handle_mcp_run_api_error_failure(self, caplog):
        """Gemini API のエラーは, 再送出されるが, ここでは記録されないか検証 (呼び出し元が 1 回だけ出力する)."""
        service_cls = _service_cm(MagicMock())
        handler = MagicMock()
        handler.run = AsyncMock(
            side_effect=APIError(429, {"error": {"message": "quota exceeded"}})
        )

        with (
            patch("code_chat_cli.mcp.McpService", service_cls),
            patch("code_chat_cli.mcp.get_gemini_client"),
            patch("code_chat_cli.mcp.QueryHandler", return_value=handler),
            pytest.raises(APIError),
        ):
            asyncio.run(handle_mcp_run("hello"))

        assert "handle_mcp_run 実行中にエラーが発生しました" not in caplog.text

    def test_handle_mcp_run_default_config_path(self):
        """設定パス未指定の場合は None が渡されるか検証."""
        service_cls = _service_cm(MagicMock())
        handler = MagicMock()
        handler.run = AsyncMock(return_value="ok")

        with (
            patch("code_chat_cli.mcp.McpService", service_cls),
            patch("code_chat_cli.mcp.get_gemini_client"),
            patch("code_chat_cli.mcp.QueryHandler", return_value=handler),
        ):
            asyncio.run(handle_mcp_run("hello"))

        service_cls.assert_called_once_with(config_path=None)


class TestHandleMcpStatus:
    """`handle_mcp_status` のテスト."""

    def test_handle_mcp_status_groups_tools_by_server_success(self, capsys):
        """ツール一覧がサーバー名ごとにまとめて表示されるか検証."""
        service = MagicMock()
        service.get_all_tools = AsyncMock(
            return_value=[
                McpToolInfo("git", "status", "show status", {}),
                McpToolInfo("git", "log", None, {}),
                McpToolInfo("fs", "read", "read file", {}),
            ]
        )

        with patch("code_chat_cli.mcp.McpService", _service_cm(service)) as service_cls:
            handle_mcp_status(config_path="conf.json")

        service_cls.assert_called_once_with(config_path=Path("conf.json"))
        out = capsys.readouterr().out
        assert "Server: git" in out
        assert "Available Tools (2):" in out
        assert "- status: show status" in out
        assert "- log: No description" in out
        assert "Server: fs" in out


class TestHandleMcpTest:
    """`handle_mcp_test` のテスト."""

    def test_handle_mcp_test_runs_connection_test_success(self):
        """handle_mcp_test が接続テストを実行するか検証."""
        service = MagicMock()
        service.test_connection = AsyncMock()

        with patch("code_chat_cli.mcp.McpService", _service_cm(service)) as service_cls:
            handle_mcp_test()

        service_cls.assert_called_once_with(config_path=None)
        service.test_connection.assert_awaited_once_with()
