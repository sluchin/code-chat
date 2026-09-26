"""Gemini CLI Tool - Constants."""

from typing import ClassVar


class Constants:
    """ファイル探索で使用する定数 (除外ディレクトリ, テキスト拡張子) を保持するクラス."""

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
