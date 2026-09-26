"""MCP ツールの情報を保持するデータクラスのモジュール."""

from dataclasses import dataclass
from typing import Any


@dataclass
class McpToolInfo:
    """MCP ツールの情報を保持するデータ構造."""

    server_name: str
    name: str
    description: str | None
    input_schema: dict[str, Any]
