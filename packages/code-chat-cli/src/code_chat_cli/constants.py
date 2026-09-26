"""Gemini CLI Tool - Constants."""

from typing import ClassVar


class Constants:
    """ファイル探索で使用する定数 (除外ディレクトリ, テキスト拡張子) などを保持するクラス."""

    DEFAULT_MAX_TOOL_ROUNDS = 20
    """MCP のツール呼び出しを繰り返す回数の既定の上限 (`--max-tool-rounds` の既定値)."""

    EXCLUDE_DIRS: ClassVar[frozenset[str]] = frozenset(
        {
            ".git",
            ".venv",
            ".env",
            "venv",
            "node_modules",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            "build",
            "dist",
            "_build",
            ".sphinx",
        }
    )

    TEXT_EXTENSIONS: ClassVar[frozenset[str]] = frozenset(
        {
            ".py",
            ".md",
            ".txt",
            ".json",
            ".yaml",
            ".yml",
            ".toml",
            ".sh",
            ".html",
            ".css",
            ".js",
            ".ts",
            ".c",
            ".cpp",
            ".h",
            ".rst",
        }
    )
