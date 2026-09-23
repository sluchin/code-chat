"""ローカル MCP サーバープロセスのライフサイクル管理および MCP 公式 SDK との通信モジュール."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters, Tool
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


class McpServerProcess:
    """MCP 公式 SDK (`mcp`) を使用してローカルの MCP サーバープロセスを起動し, Stdio パイプ通信経由でツール取得や呼び出しを仲介するクラス."""

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        """McpServerProcess インスタンスを初期化します.

        Args:
            command (str): 実行コマンド (例: "uvx", "node", "python").
            args (list[str] | None): 引数リスト (例: ["mcp-server-git"]).
            env (dict[str, str] | None): 環境変数 (省略時は親プロセスの環境変数を継承).

        """
        self.command = command
        self.args = self._resolve_args(args or [])
        self.env = env
        logger.debug(
            "MCPサーバプロセス: %s %s",
            self.command,
            " ".join(self.args),
        )

        self._server_params = StdioServerParameters(
            command=self.command,
            args=self.args,
            env=self.env,
        )

    @asynccontextmanager
    async def connect(self) -> AsyncGenerator[ClientSession, None]:
        """サブプロセスとして MCP サーバーを起動し, Stdio パイプによるセッションを確立します.

        Yields:
            ClientSession: 初期化済みの MCP クライアントセッション.

        """
        logger.info(
            "MCP サーバープロセスを起動します: %s %s",
            self.command,
            " ".join(self.args),
        )

        # read / write 変数を try ブロック外で宣言・初期化 (E0601 対策)
        read = None
        write = None

        try:
            # MCP 公式 SDK の stdio_client でサブプロセスの標準入出力をパイプ接続
            async with (
                stdio_client(self._server_params) as (read, write),
                ClientSession(read, write) as session,
            ):
                # JSON-RPC によるハンドシェイク初期化
                await session.initialize()
                logger.debug("MCP サーバーセッションの初期化が完了しました")
                yield session
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error(
                "MCP サーバープロセスの通信中にエラーが発生しました (%s %s): %s",
                self.command,
                " ".join(self.args),
                e,
            )
            raise

    async def get_tools(self) -> list[Tool]:
        """MCP サーバーから公開されているツールの生データ (mcp.Tool オブジェクトのリスト) を取得します.

        Returns:
            list[Tool]: 取得したツールのリスト. 取得失敗時は空リストを返します.

        """
        try:
            async with self.connect() as session:
                response = await session.list_tools()
                logger.info("%d 個の MCP ツールを取得しました", len(response.tools))
                return response.tools
        except Exception:  # noqa: BLE001  # fmt: skip # pylint: disable=broad-exception-caught
            # トレースバックを抑止
            return []

    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any] | None = None
    ) -> Any:
        """指定した MCP ツールをサーバー側で実行し, 結果を返却します.

        Args:
            tool_name (str): 実行するツール名 (例: "git_status").
            arguments (dict[str, Any] | None, optional): ツールに引き渡す引数辞書. Defaults to None.

        Returns:
            Any: サーバーからの実行結果レスポンス.

        """
        async with self.connect() as session:
            logger.info("MCP ツール '%s' を実行します...", tool_name)
            result = await session.call_tool(tool_name, arguments=arguments or {})
            return result

    def _resolve_args(self, args: list[str]) -> list[str]:
        """設定ファイル内のコマンド引数に含まれる変数を解決します.

        引数リスト内に含まれる環境変数テンプレート (例: `${CWD}`) を
        現在の実行環境における実際の値 (カレントディレクトリの絶対パス等) に置換します.

        Args:
            args (list[str]): 置換対象の引数文字列リスト.

        Returns:
            list[str]: 変数が置換された引数文字列リスト.

        """
        if not args:
            return []
        # 実行時のカレントディレクトリの絶対パス（/home/higashi/src/code-chat 等）を取得
        current_dir = str(Path.cwd().resolve())

        # "${CWD}" をカレントディレクトリの絶対パスに置換
        return [arg.replace("${CWD}", current_dir) for arg in args]
