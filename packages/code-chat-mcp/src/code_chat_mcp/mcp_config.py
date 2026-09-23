"""MCP サーバー設定用モジュール."""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class McpServerConfig:
    """個別の MCP サーバー設定."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True


class McpConfig:
    """MCP サーバーの接続設定および環境設定を管理するクラス.

    設定ファイル (JSON等) のロード・検証を行い,
    各 MCP サーバーの起動パラメータ (コマンド, 引数, 環境変数など) を保持します.
    """

    def __init__(self, config_path: Path | None = None) -> None:
        """設定ファイルをロードして McpConfig を初期化します.

        Args:
            config_path (Path | None): MCP 設定ファイルのパス. 省略時はデフォルトパスを使用.

        """
        path = config_path or Path.home() / ".config" / "code-chat" / "mcp.json"
        self.config_path = path
        self.servers: dict[str, McpServerConfig] = self.load_mcp_config()

    def load_mcp_config(self) -> dict[str, McpServerConfig]:
        """設定ファイル (mcp.json) から MCP サーバー設定を読み込みます.

        Returns:
            dict[str, McpServerConfig]: サーバー名をキー, サーバー設定オブジェクトを値とする辞書.

        """
        if not self.config_path.exists():
            logger.warning("MCP 設定ファイルが見つかりません: %s", self.config_path)
            return {}

        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            servers = {}
            for name, cfg in data.get("mcpServers", {}).items():
                # "enabled" または "enable" フィールドのチェック (デフォルトは True)
                is_enabled = cfg.get("enabled", cfg.get("enable", True))
                if not is_enabled:
                    logger.info(
                        "MCP サーバー '%s' は無効化 (enabled: false) されているためスキップします",
                        name,
                    )
                    continue

                servers[name] = McpServerConfig(
                    name=name,
                    command=cfg.get("command", ""),
                    args=cfg.get("args", []),
                    env=cfg.get("env", {}),
                    enabled=cfg.get("enabled", True),
                )
            return servers
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("MCP 設定ファイルの読み込みに失敗しました")
            return {}
