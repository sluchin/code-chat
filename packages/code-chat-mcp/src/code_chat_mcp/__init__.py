"""code-chat-mcp package."""

from code_chat_mcp.mcp_config import McpConfig
from code_chat_mcp.mcp_server_connection import McpServerConnection
from code_chat_mcp.mcp_service import McpService

__version__ = "0.1.0"

__all__ = [
    "McpConfig",
    "McpServerConnection",
    "McpService",
    "__version__",
]
