"""`code_chat_cli.cache_error` モジュールのテスト."""

import pytest

from code_chat_cli.cache_error import CacheError


class TestCacheError:
    """`CacheError` のテスト."""

    def test_cache_error_success(self):
        """Exception を継承し, メッセージを保持して送出・捕捉できるか検証."""
        assert issubclass(CacheError, Exception)

        with pytest.raises(CacheError, match="boom") as exc_info:
            raise CacheError("boom")

        assert str(exc_info.value) == "boom"
