"""`code_chat_lib.gemini_error_kind` モジュールのテスト."""

import pytest

from code_chat_lib.gemini_error_kind import GeminiErrorKind


class TestGeminiErrorKind:
    """`GeminiErrorKind` のテスト."""

    def test_gemini_error_kind_http_codes_success(self):
        """HTTP ステータスが, Gemini API の仕様どおりの値で定義されているか検証."""
        kind = GeminiErrorKind

        assert kind.HTTP_BAD_REQUEST == 400
        assert kind.HTTP_FORBIDDEN == 403
        assert kind.HTTP_NOT_FOUND == 404
        assert kind.HTTP_TOO_MANY_REQUESTS == 429
        assert kind.HTTP_INTERNAL_SERVER_ERROR == 500
        assert kind.HTTP_SERVICE_UNAVAILABLE == 503
        assert kind.HTTP_GATEWAY_TIMEOUT == 504

    def test_gemini_error_kind_status_by_http_code_success(self):
        """HTTP ステータスから補う status が, すべての HTTP ステータス (400 は INVALID_ARGUMENT) に対して定義されているか検証."""
        expected = {
            400: "INVALID_ARGUMENT",
            403: "PERMISSION_DENIED",
            404: "NOT_FOUND",
            429: "RESOURCE_EXHAUSTED",
            500: "INTERNAL",
            503: "UNAVAILABLE",
            504: "DEADLINE_EXCEEDED",
        }

        assert dict(GeminiErrorKind.STATUS_BY_HTTP_CODE) == expected
        assert GeminiErrorKind.STATUS_FAILED_PRECONDITION == "FAILED_PRECONDITION"

    def test_gemini_error_kind_markers_success(self):
        """原因を判別する文字列が, 定義されているか検証."""
        kind = GeminiErrorKind

        assert kind.QUOTA_PER_DAY == "PerDay"
        assert kind.QUOTA_PER_MINUTE == "PerMinute"
        assert kind.QUOTA_CACHED_CONTENT_STORAGE == "CachedContentStorage"
        assert kind.TIER_FREE == "FreeTier"
        assert kind.MESSAGE_API_KEY_INVALID == "API key not valid"
        assert kind.MESSAGE_CACHE_TOO_SMALL == "too small"
        assert kind.REASON_SCOPE_INSUFFICIENT == "ACCESS_TOKEN_SCOPE_INSUFFICIENT"

    def test_gemini_error_kind_retryable_success(self):
        """リトライの対象が, 503 / 429 と, 対応するキーワードになっているか検証."""
        assert GeminiErrorKind.RETRYABLE_HTTP_CODES == (503, 429)
        assert GeminiErrorKind.RETRYABLE_KEYWORDS == (
            "503",
            "UNAVAILABLE",
            "429",
            "RESOURCE_EXHAUSTED",
        )

    def test_gemini_error_kind_status_by_http_code_is_read_only(self):
        """status の対応表が, 実行中に書き換えられないか検証."""
        with pytest.raises(TypeError):
            GeminiErrorKind.STATUS_BY_HTTP_CODE[999] = "X"  # type: ignore[index]
