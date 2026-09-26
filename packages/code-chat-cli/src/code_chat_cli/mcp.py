"""CLI や対話型セッションから呼び出される MCP サービスラッパーモジュール."""

import asyncio
from collections import defaultdict
from pathlib import Path

from code_chat_mcp.mcp_service import McpService
from code_chat_mcp.mcp_tool_info import McpToolInfo

from code_chat_cli.client import get_gemini_client
from code_chat_cli.logger import get_logger
from code_chat_cli.query_handler import QueryHandler

logger = get_logger(__name__)


async def handle_mcp_run(
    user_prompt: str,
    config_path: Path | str | None = None,
    use_oauth: bool = False,
) -> str:
    """McpService のライフサイクルを管理し, Gemini へのクエリとツール実行を行います.

    `chat.py` 等の非同期文脈からメイン処理として呼び出すエンドポイント関数です。

    Args:
        user_prompt (str): ユーザーから入力されたプロンプト文字列.
        config_path (Path | str | None): MCP 設定ファイルのパス. 省略時はデフォルトパスを使用.

    Returns:
        str: Gemini からの最終回答テキスト.

    """
    try:
        config = Path(config_path) if config_path else None
        logger.debug("McpService の初期化とプロセスの起動を開始します")

        # async with で MCP サーバープロセスの自動起動・自動クリーンアップを行う
        async with McpService(config_path=config) as mcp_service:
            # クライアントの初期化（API キーまたは OAuth 認証）
            client = get_gemini_client(use_oauth=use_oauth)
            handler = QueryHandler(gemini_client=client, mcp_service=mcp_service)

            logger.info("ユーザープロンプトの処理を開始します: %s", user_prompt)
            result_text = await handler.run(user_prompt)
            return result_text

    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("handle_mcp_run 実行中にエラーが発生しました")
        raise


def handle_mcp_status(config_path: Path | str | None = None) -> None:
    """`code-chat mcp status` 等の CLI コマンドから呼び出されるステータス確認ロジック.

    Args:
        config_path (Path | str | None, optional): MCP 設定ファイルのパス. 省略時はデフォルトパスを使用. Defaults to None.

    """

    async def _status() -> None:
        config = Path(config_path) if config_path else None
        async with McpService(config_path=config) as mcp_service:
            all_tools = await mcp_service.get_all_tools()

            # 取得したツール一覧 (list[McpToolInfo]) をサーバー名ごとにグループ化
            tools_by_server: dict[str, list[McpToolInfo]] = defaultdict(list)
            for tool in all_tools:
                tools_by_server[tool.server_name].append(tool)

            print("--- [MCP Servers Status] ---")
            for server_name, tools in tools_by_server.items():
                print(f"Server: {server_name}")
                print(f"  Available Tools ({len(tools)}):")
                for tool in tools:
                    print(f"    - {tool.name}: {tool.description or 'No description'}")

    asyncio.run(_status())


def handle_mcp_test(config_path: Path | str | None = None) -> None:
    """mcp.json に定義された MCP サーバーへの接続およびツール一覧取得テストを行います.

    Args:
        config_path (Path | str | None, optional): MCP 設定ファイルのパス. 省略時はデフォルトパスを使用. Defaults to None.

    """

    async def _test() -> None:
        config = Path(config_path) if config_path else None
        async with McpService(config_path=config) as mcp_service:
            await mcp_service.test_connection()

    asyncio.run(_test())
