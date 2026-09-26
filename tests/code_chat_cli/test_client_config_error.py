"""`code_chat_cli.client_config_error` モジュールのテスト."""

import pytest

from code_chat_cli.client_config_error import ClientConfigError


class TestClientConfigError:
    """`ClientConfigError` のテスト."""

    def test_client_config_error_success(self):
        """Exception を継承し, メッセージを保持して送出・捕捉できるか検証."""
        assert issubclass(ClientConfigError, Exception)

        with pytest.raises(ClientConfigError, match="boom") as exc_info:
            raise ClientConfigError("boom")

        assert str(exc_info.value) == "boom"
