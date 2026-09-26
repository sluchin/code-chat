"""MCP サーバー管理およびライフサイクル制御を行うサービスクラス."""

import logging
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from code_chat_mcp.mcp_config import McpConfig
from code_chat_mcp.mcp_server_config import McpServerConfig
from code_chat_mcp.mcp_server_connection import McpServerConnection
from code_chat_mcp.mcp_tool_info import McpToolInfo

logger = logging.getLogger(__name__)


class McpService:
    """CLI サブコマンド等から呼び出され, MCP サーバーへの接続の管理・テストを実行するサービス."""

    def __init__(self, config_path: Path | None = None) -> None:
        """設定ファイルをロードして McpService を初期化します.

        Args:
            config_path (Path | None): MCP 設定ファイルのパス. 省略時はデフォルトパスを使用.

        """
        self.config_path = config_path
        config = McpConfig(config_path)
        self.servers: dict[str, McpServerConfig] = config.servers
        # _connections 属性を初期化
        self._connections: dict[str, McpServerConnection] = {}

    async def __aenter__(self) -> Self:
        """非同期コンテキストマネージャーのエントリーポイント.

        Returns:
            Self: McpService インスタンス.

        """
        await self._start_all_servers()
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
        await self._stop_all_servers()

    async def get_all_tools(self) -> list[McpToolInfo]:
        """有効化されている全 MCP サーバーからツール一覧を取得します.

        Returns:
            list[McpToolInfo]: 取得したツール情報のリスト.

        """
        all_tools: list[McpToolInfo] = []

        for server_name, config in self.servers.items():
            if not config.enabled:
                continue

            connection = McpServerConnection(
                command=config.command,
                args=config.args,
                env=config.env or None,
            )

            try:
                # McpServerConnection からツール一覧を取得
                tools = await connection.get_tools()
                for tool in tools:
                    all_tools.append(
                        McpToolInfo(
                            server_name=server_name,
                            name=tool.name,
                            description=tool.description,
                            input_schema=tool.inputSchema,
                        )
                    )
            # 1 台のサーバーの失敗で, 他のサーバーの処理を止めない.
            # MCP サーバー (外部プロセス) 由来の例外は, MCP SDK・anyio (ExceptionGroup)・OSError など多岐にわたるため, 広く捕捉する.
            # 通信の詳細は, McpServerConnection.connect が記録済みのため, ここでは, どのサーバーかだけを記録する.
            except Exception:  # noqa: BLE001 # pylint: disable=broad-exception-caught
                logger.error(
                    "MCP サーバー '%s' からのツール取得に失敗しました", server_name
                )

        return all_tools

    async def test_connection(self) -> None:
        """設定ファイル (mcp.json) に登録された全 MCP サーバーに接続し, ツール一覧取得テストを行います."""
        if not self.servers:
            print("テスト対象の MCP サーバーが登録されていません")
            return

        print("=== Testing MCP Server Connections via Stdio ===")

        await self._test_servers_async()

    async def _start_all_servers(self) -> None:
        """有効になっている全 MCP サーバーへの接続を登録します."""
        for name, config in self.servers.items():
            if not config.enabled:
                continue
            connection = McpServerConnection(
                command=config.command,
                args=config.args,
                env=config.env or None,
            )
            self._connections[name] = connection

    async def _stop_all_servers(self) -> None:
        """登録済みの全 MCP サーバーへの接続を破棄・クリーンアップします."""
        # 接続は, ツールの呼び出しごとにサブプロセスを起動・終了するため, 登録を破棄するだけでよい
        self._connections.clear()

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
        connection = self._connections.get(server_name)
        if not connection:
            raise ValueError(f"Server '{server_name}' is not running.")
        return await connection.call_tool(tool_name, arguments or {})

    async def _test_servers_async(self) -> None:
        """MCP サーバー群に対して順番に Stdio 接続を行い, ツールを取得できるかテストします."""
        success_count = 0
        server_list = list(self.servers.values())

        for config in server_list:
            if not config.enabled:
                print(f"[{config.name}] ... [SKIP] (Disabled)")
                continue

            print(f"[{config.name}] Connecting... ", end="", flush=True)

            connection = McpServerConnection(
                command=config.command,
                args=config.args,
                env=config.env or None,
            )

            try:
                # 実際に Stdio セッションを開き, list_tools を呼び出す
                tools = await connection.get_tools()
                print(f"[OK] Successfully fetched {len(tools)} tools.")

                # 取得したツール名を軽くプレビュー表示
                for tool in tools:
                    desc = tool.description or "No description"
                    print(f"   └─ {tool.name}: {desc}")

                success_count += 1
            # 接続の失敗も結果として集計するため, 1 台の失敗で処理を止めない.
            # MCP サーバー (外部プロセス) 由来の例外は, MCP SDK・anyio (ExceptionGroup)・OSError など多岐にわたるため, 広く捕捉する.
            except Exception:  # noqa: BLE001 # pylint: disable=broad-exception-caught
                print("[NG] Failed to connect.")
                logger.error("サーバー '%s' への接続テスト失敗", config.name)

        print(
            f"\nテスト完了: {success_count}/{len(server_list)} サーバーが正常に応答しました"
        )
