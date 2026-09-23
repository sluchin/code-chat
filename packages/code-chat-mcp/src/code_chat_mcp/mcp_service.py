"""MCP サーバー管理およびライフサイクル制御を行うサービスクラス."""

import asyncio
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from code_chat_mcp.mcp_config import McpConfig, McpServerConfig
from code_chat_mcp.mcp_server_process import McpServerProcess

logger = logging.getLogger(__name__)


@dataclass
class McpToolInfo:
    """MCP ツールの情報を保持するデータ構造."""

    server_name: str
    name: str
    description: str | None
    input_schema: dict[str, Any]


class McpService:
    """CLI サブコマンド等から呼び出され, MCP サーバープロセスの管理・テストを実行するサービス."""

    def __init__(self, config_path: Path | None = None) -> None:
        """設定ファイルをロードして McpService を初期化します.

        Args:
            config_path (Path | None): MCP 設定ファイルのパス. 省略時はデフォルトパスを使用.

        """
        self.config_path = config_path
        config = McpConfig(config_path)
        self.servers: dict[str, McpServerConfig] = config.load_mcp_config()
        # _processes 属性を初期化
        self._processes: dict[str, McpServerProcess] = {}

    async def __aenter__(self) -> Self:
        """非同期コンテキストマネージャーのエントリーポイント.

        Returns:
            Self: McpService インスタンス.

        """
        await self.start_all_servers()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """非同期コンテキストマネージャーのクリーンアップ処理.

        Args:
            exc_type (type[BaseException] | None): 例外の型.
            exc_val (BaseException | None): 例外オブジェクト.
            exc_tb (TracebackType | None): トレースバックオブジェクト.

        """
        await self.stop_all_servers()

    def run(
        self, server_name: str, tool_name: str, arguments: dict | None = None
    ) -> None:
        """単体テスト用: MCP ツールを直接実行して結果を出力します.

        Args:
            server_name (str): 実行対象の MCP サーバー名.
            tool_name (str): 実行するツール名.
            arguments (dict | None): ツールに引き渡す引数辞書.

        """
        server = self._get_server_or_fail(server_name)
        process = McpServerProcess(
            command=server.command,
            args=server.args,
            env=server.env or None,
        )

        async def _run() -> None:
            result = await process.call_tool(tool_name, arguments or {})
            print(f"=== Execution Result: {tool_name} ===")
            print(result)

        asyncio.run(_run())

    async def get_all_tools(self) -> list[McpToolInfo]:
        """有効化されている全 MCP サーバーからツール一覧を取得します.

        Returns:
            list[McpToolInfo]: 取得したツール情報のリスト.

        """
        all_tools: list[McpToolInfo] = []

        for server_name, config in self.servers.items():
            if not config.enabled:
                continue

            process = McpServerProcess(
                command=config.command,
                args=config.args,
                env=config.env or None,
            )

            try:
                # McpServerProcess からツール一覧を取得
                tools = await process.get_tools()
                for tool in tools:
                    all_tools.append(
                        McpToolInfo(
                            server_name=server_name,
                            name=tool.name,
                            description=getattr(tool, "description", None),
                            input_schema=getattr(
                                tool,
                                "inputSchema",
                                getattr(tool, "input_schema", {}),
                            ),
                        )
                    )
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception(
                    "MCP サーバー '%s' からのツール取得に失敗しました",
                    server_name,
                )

        return all_tools

    def show_status(self) -> None:
        """登録されている MCP サーバーの一覧と設定状態を表示します."""
        if not self.servers:
            print("登録されている MCP サーバーはありません")
            return

        print("=== Registered MCP Servers ===")
        print(f"{'SERVER NAME':<20} {'ENABLED':<10} {'COMMAND':<30}")
        print("-" * 65)

        for name, config in self.servers.items():
            status_str = "Enabled" if config.enabled else "Disabled"
            cmd_str = f"{config.command} {' '.join(config.args)}".strip()
            if len(cmd_str) > 30:
                cmd_str = cmd_str[:27] + "..."
            print(f"{name:<20} {status_str:<10} {cmd_str:<30}")

    def test_connection(self) -> None:
        """設定ファイル (mcp.json) に登録された全 MCP サーバーに接続し, ツール一覧取得テストを行います."""
        if not self.servers:
            print("テスト対象の MCP サーバーが登録されていません")
            return

        print("=== Testing MCP Server Connections via Stdio ===")

        # 非同期テスト処理を同期で実行
        asyncio.run(self._test_servers_async())

    async def start_all_servers(self) -> None:
        """有効になっている全 MCP サーバープロセスを起動します."""
        for name, config in self.servers.items():
            if not config.enabled:
                continue
            process = McpServerProcess(
                command=config.command,
                args=config.args,
                env=config.env or None,
            )
            self._processes[name] = process

    async def stop_all_servers(self) -> None:
        """起動中の全 MCP サーバープロセスを停止・クリーンアップします."""
        self._processes.clear()

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        """指定した MCP サーバーのツールを実行します.

        Args:
            server_name (str): 実行対象の MCP サーバー名.
            tool_name (str): 実行するツール名.
            arguments (dict[str, Any] | None): ツールに引き渡す引数辞書.

        Returns:
            Any: ツール実行結果.

        """
        process = self._processes.get(server_name)
        if not process:
            raise ValueError(f"Server '{server_name}' is not running.")
        return await process.call_tool(tool_name, arguments or {})

    def _get_server_or_fail(self, server_name: str) -> McpServerConfig:
        """サーバー名が存在するか検証し, 無ければ終了します.

        Args:
            server_name (str): 検証対象のサーバー名.

        Returns:
            McpServerConfig: サーバー設定オブジェクト.

        """
        server = self.servers.get(server_name)
        if not server:
            logger.error(
                "指定された MCP サーバー '%s' は設定に存在しません",
                server_name,
            )
            sys.exit(1)
        return server

    async def _test_servers_async(self) -> None:
        """MCP サーバー群に対して順番に Stdio 接続を行い, ツールを取得できるかテストします."""
        success_count = 0
        server_list = list(self.servers.values())

        for config in server_list:
            if not config.enabled:
                print(f"[{config.name}] ... [SKIP] (Disabled)")
                continue

            print(f"[{config.name}] Connecting... ", end="", flush=True)

            process = McpServerProcess(
                command=config.command,
                args=config.args,
                env=config.env or None,
            )

            try:
                # 実際に Stdio セッションを開き, list_tools を呼び出す
                tools = await process.get_tools()
                print(f"[OK] Successfully fetched {len(tools)} tools.")

                # 取得したツール名を軽くプレビュー表示
                for tool in tools:
                    desc = getattr(tool, "description", None) or "No description"
                    print(f"   └─ {tool.name}: {desc}")

                success_count += 1
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception("サーバー '%s' への接続テスト失敗", config.name)

        print(
            f"\nテスト完了: {success_count}/{len(server_list)} サーバーが正常に応答しました"
        )

    def _format_tools_for_gemini(
        self, mcp_tools: list[McpToolInfo]
    ) -> list[dict[str, Any]]:
        """MCP ツール一覧を Gemini API 用の function_declarations 形式に変換します.

        名前の衝突を防ぐため, "server_name__tool_name" 形式に変換します.

        Args:
            mcp_tools (list[McpToolInfo]): MCP ツール情報のリスト.

        Returns:
            list[dict[str, Any]]: Gemini API 用の関数宣言リスト.

        """
        declarations: list[dict[str, Any]] = []

        for tool in mcp_tools:
            formatted_name = f"{tool.server_name}__{tool.name}"

            declaration = {
                "name": formatted_name,
                "description": tool.description or "",
                "parameters": tool.input_schema,
            }
            declarations.append(declaration)

        return declarations
