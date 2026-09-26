"""`code_chat_lib.constants` モジュールのテスト."""

from code_chat_lib.constants import Constants


class TestConstants:
    """`Constants` のテスト."""

    def test_constants_success(self):
        """除外ディレクトリとテキスト拡張子が, 想定した値を含む文字列の集合で定義されているか検証."""
        assert {
            ".git",
            ".venv",
            "__pycache__",
            "node_modules",
        } <= Constants.EXCLUDE_DIRS
        assert {".py", ".md", ".json"} <= Constants.TEXT_EXTENSIONS
        assert all(ext.startswith(".") for ext in Constants.TEXT_EXTENSIONS)
        assert not Constants.EXCLUDE_DIRS & Constants.TEXT_EXTENSIONS
