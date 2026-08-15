"""Gemini CLI Tool - Constants."""

EXCLUDE_DIRS: set[str] = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "build",
    "dist",
    "_build",
    ".sphinx",
}

TEXT_EXTENSIONS: set[str] = {
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
