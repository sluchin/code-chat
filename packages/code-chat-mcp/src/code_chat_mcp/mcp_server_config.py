"""個別の MCP サーバー設定を保持するデータクラスのモジュール."""

from dataclasses import dataclass, field


@dataclass
class McpServerConfig:
    """個別の MCP サーバー設定."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
