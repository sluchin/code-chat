"""`code_chat_cli.oauth_error` モジュールのテスト."""

import pytest

from code_chat_cli.oauth_error import OAuthError


class TestOAuthError:
    """`OAuthError` のテスト."""

    def test_oauth_error_success(self):
        """Exception を継承し, メッセージを保持して送出・捕捉できるか検証."""
        assert issubclass(OAuthError, Exception)

        with pytest.raises(OAuthError, match="boom") as exc_info:
            raise OAuthError("boom")

        assert str(exc_info.value) == "boom"
