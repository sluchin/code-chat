"""`code_chat_lib.gemini_error` モジュールのテスト."""

import pytest
from google.genai.errors import APIError, ClientError

from code_chat_lib.gemini_error import (
    _first_line,
    _http_code,
    _quota_detail,
    _retry_suffix,
    find_api_error,
    find_cause,
    format_error,
    hint_for_error,
    is_daily_quota_error,
    retry_delay_seconds,
    summarize_error,
)


def _error(code, status, message, violations=None, retry_delay=None):
    """Gemini API の実際のレスポンス形式に近い APIError を作成する."""
    details = []
    if violations:
        details.append(
            {
                "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                "violations": [{"quotaId": v} for v in violations],
            }
        )
    if retry_delay:
        details.append(
            {
                "@type": "type.googleapis.com/google.rpc.RetryInfo",
                "retryDelay": retry_delay,
            }
        )
    body = {"error": {"code": code, "status": status, "message": message}}
    if details:
        body["error"]["details"] = details
    return ClientError(code, body)


DAILY = _error(
    429,
    "RESOURCE_EXHAUSTED",
    "You exceeded your current quota.\n* Quota exceeded for metric: x, limit: 20, model: gemini-3.8-flash\nPlease retry in 49.8s.",
    ["GenerateRequestsPerDayPerProjectPerModel-FreeTier"],
    "49s",
)
MINUTE = _error(
    429,
    "RESOURCE_EXHAUSTED",
    "Quota exceeded, limit: 5, model: gemini-flash",
    ["GenerateRequestsPerMinutePerProjectPerModel-FreeTier"],
    "30s",
)
CACHE_FREE = _error(
    429,
    "RESOURCE_EXHAUSTED",
    "TotalCachedContentStorageTokensPerModelFreeTier limit exceeded for model gemini-3.8-flash: limit=0",
    ["TotalCachedContentStorageTokensPerModelFreeTier"],
)


class TestFindCause:
    """`find_cause` のテスト."""

    def test_find_cause_success(self):
        """指定した種類の例外と, それを原因に持つ例外から, 指定した種類の例外が見つかるか検証."""
        error = ValueError("x")
        wrapped = RuntimeError("wrapped")
        wrapped.__cause__ = error

        assert find_cause(error, ValueError) is error
        assert find_cause(wrapped, ValueError) is error

    def test_find_cause_other(self):
        """指定した種類の例外を含まない例外・None では, None が返るか検証."""
        assert find_cause(RuntimeError("x"), ValueError) is None
        assert find_cause(None, ValueError) is None


class TestFindApiError:
    """`find_api_error` のテスト."""

    def test_find_api_error_success(self):
        """APIError と, それを原因 (`__cause__` / `__context__`) に持つ例外から, APIError が見つかるか検証."""
        error = APIError(500, {"error": {"message": "x"}})
        caused = RuntimeError("wrapped")
        caused.__cause__ = error
        contexted = RuntimeError("wrapped")
        contexted.__context__ = error

        assert find_api_error(error) is error
        assert find_api_error(caused) is error
        assert find_api_error(contexted) is error

    def test_find_api_error_other(self):
        """Gemini API と無関係な例外・None では, None が返るか検証."""
        assert find_api_error(RuntimeError("x")) is None
        assert find_api_error(None) is None

    def test_find_api_error_cyclic_cause(self):
        """原因が循環している例外でも, 無限ループせずに None が返るか検証."""
        first = RuntimeError("a")
        second = RuntimeError("b")
        first.__cause__ = second
        second.__cause__ = first

        assert find_api_error(first) is None


class TestRetryDelaySeconds:
    """`retry_delay_seconds` のテスト."""

    @pytest.mark.parametrize(
        ("message", "expected"),
        [
            ("Resource exhausted. retryDelay: '32s' Please wait.", 32.0),
            ("Resource exhausted. retryDelay: '32.5s' Please wait.", 32.5),
            ("Error occurred retryDelay: 10s in stream", 10.0),
            ("Quota exceeded without delay info", None),
            ("retryDelay: 'abc's", None),
        ],
    )
    def test_retry_delay_seconds_success(self, message, expected):
        """様々なエラーメッセージの形式から推奨待機秒数を取り出し, 無い場合は None が返るか検証."""
        assert retry_delay_seconds(Exception(message)) == expected


class TestIsDailyQuotaError:
    """`is_daily_quota_error` のテスト."""

    def test_is_daily_quota_error_success(self):
        """1 日あたりの上限のエラーだけが True になるか検証."""
        assert is_daily_quota_error(DAILY) is True
        assert is_daily_quota_error(Exception("Quota exceeded (PerDay)")) is True
        assert is_daily_quota_error(MINUTE) is False


class TestSummarizeError:
    """`summarize_error` のテスト."""

    def test_summarize_error_daily_success(self):
        """無料枠の 1 日あたりの上限は, モデル名と上限値を含み, 再試行の案内は含まないか検証."""
        summary = summarize_error(DAILY)

        assert summary.startswith("[HTTP 429 RESOURCE_EXHAUSTED] ")
        assert "無料枠の 1 日あたりのリクエスト上限に到達しました" in summary
        assert "モデル: gemini-3.8-flash" in summary
        assert "上限: 20 件" in summary
        assert "再試行" not in summary

    def test_summarize_error_daily_without_tier_success(self):
        """無料枠でない 1 日あたりの上限は, 「無料枠の」が付かないか検証."""
        error = _error(429, "RESOURCE_EXHAUSTED", "x", ["GenerateRequestsPerDay"])

        assert "1 日あたりのリクエスト上限" in summarize_error(error)
        assert "無料枠" not in summarize_error(error)

    def test_summarize_error_minute_success(self):
        """1 分あたりの上限は, 再試行できるまでの秒数を含むか検証."""
        summary = summarize_error(MINUTE)

        assert "1 分あたりのリクエスト上限に到達しました" in summary
        assert "約 30 秒後に再試行できます" in summary

    def test_summarize_error_other_429_success(self):
        """種類が特定できない 429 は, 汎用の文言になるか検証."""
        error = _error(429, "RESOURCE_EXHAUSTED", "Quota exceeded")

        assert "リクエストの上限に到達しました" in summarize_error(error)

    def test_summarize_error_cache_free_tier_success(self):
        """無料枠でのキャッシュ保存は, Context Caching が使えない旨になるか検証."""
        assert "無料枠では Context Caching を利用できません" in summarize_error(
            CACHE_FREE
        )

    def test_summarize_error_503_success(self):
        """503 は, モデルの高負荷である旨になるか検証."""
        error = _error(503, "UNAVAILABLE", "high demand")

        assert "モデルが高負荷" in summarize_error(error)

    def test_summarize_error_404_success(self):
        """404 は, メッセージの 1 行目を含むか検証."""
        error = _error(404, "NOT_FOUND", "models/x is no longer available\nsecond line")

        summary = summarize_error(error)

        assert "見つかりません: models/x is no longer available" in summary
        assert "second line" not in summary

    def test_summarize_error_invalid_api_key_success(self):
        """無効な API キーは, その旨になるか検証."""
        error = _error(
            400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key."
        )

        assert "API キーが無効です" in summarize_error(error)

    @pytest.mark.parametrize(
        ("message", "expected"),
        [
            (
                "Cached content is too small. min_total_token_count=1024",
                "(最小 1024 トークン)",
            ),
            ("Cached content is too small", "小さすぎます"),
        ],
    )
    def test_summarize_error_cache_too_small_success(self, message, expected):
        """キャッシュ対象が小さすぎる場合は, 最小トークン数 (分かる場合) を含むか検証."""
        error = _error(400, "INVALID_ARGUMENT", message)

        assert expected in summarize_error(error)

    def test_summarize_error_scope_success(self):
        """OAuth のスコープ不足は, その旨になるか検証."""
        error = _error(403, "PERMISSION_DENIED", "ACCESS_TOKEN_SCOPE_INSUFFICIENT")

        assert "スコープが不足" in summarize_error(error)

    def test_summarize_error_default_success(self):
        """特別な扱いのないエラーは, メッセージの 1 行目が使われ, 長い場合は切り詰められるか検証."""
        error = _error(400, "INVALID_ARGUMENT", "x" * 500)

        summary = summarize_error(error)

        assert summary.startswith("[HTTP 400 INVALID_ARGUMENT] xxx")
        assert len(summary) < 260

    def test_summarize_error_status_from_http_code_success(self):
        """status が無い場合は, HTTP ステータスから status が補われるか検証."""
        error = APIError(500, {"error": {"message": "boom"}})

        assert summarize_error(error).startswith("[HTTP 500 INTERNAL] ")

    def test_summarize_error_without_status_success(self):
        """status が無く, HTTP ステータスからも補えない場合は, HTTP ステータスだけで概要が作れるか検証."""
        error = APIError(418, {"error": {"message": "boom"}})

        assert summarize_error(error) == "[HTTP 418] boom"

    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (_error(500, "INTERNAL", "boom"), "内部エラー"),
            (
                _error(504, "DEADLINE_EXCEEDED", "boom"),
                "制限時間内に終わりませんでした",
            ),
            (
                _error(400, "FAILED_PRECONDITION", "boom"),
                "課金の設定なしに利用できません",
            ),
        ],
    )
    def test_summarize_error_other_kinds_success(self, error, expected):
        """500 / 504 / 前提条件エラー (FAILED_PRECONDITION) が, それぞれの文言になるか検証."""
        assert expected in summarize_error(error)


class TestHintForError:
    """`hint_for_error` のテスト."""

    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (CACHE_FREE, "有料枠"),
            (DAILY, "翌日まで回復しません"),
            (MINUTE, "自動でリトライします"),
            (_error(429, "RESOURCE_EXHAUSTED", "Quota"), "原因の候補"),
            (_error(503, "UNAVAILABLE", "x"), "一時的な混雑"),
            (_error(500, "INTERNAL", "x"), "Google 側の一時的な問題"),
            (_error(504, "DEADLINE_EXCEEDED", "x"), "コンテキスト"),
            (_error(400, "FAILED_PRECONDITION", "x"), "請求先アカウント"),
            (_error(404, "NOT_FOUND", "x"), "--list-models"),
            (_error(400, "INVALID_ARGUMENT", "API key not valid"), "GEMINI_API_KEY"),
            (_error(400, "INVALID_ARGUMENT", "too small"), "キャッシュを使わずに"),
            (
                _error(403, "PERMISSION_DENIED", "ACCESS_TOKEN_SCOPE_INSUFFICIENT"),
                "--oauth",
            ),
        ],
    )
    def test_hint_for_error_success(self, error, expected):
        """原因に応じたヒントが返るか検証."""
        assert expected in hint_for_error(error)

    def test_hint_for_error_none(self):
        """該当するヒントがないエラーでは, None が返るか検証."""
        assert hint_for_error(_error(401, "UNAUTHENTICATED", "x")) is None


class TestFormatError:
    """`format_error` のテスト."""

    def test_format_error_success(self):
        """Gemini API のエラーは, 概要とヒントに整理され, 辞書の全文を含まないか検証."""
        text = format_error(DAILY)

        assert "[HTTP 429 RESOURCE_EXHAUSTED]" in text
        assert "\n  ヒント: " in text
        assert "'error'" not in text

    def test_format_error_wrapped_success(self):
        """Gemini API のエラーを包んだ例外でも, 整理されるか検証."""
        wrapped = RuntimeError("wrapped")
        wrapped.__cause__ = DAILY

        assert "[HTTP 429" in format_error(wrapped)

    def test_format_error_without_hint_success(self):
        """ヒントがないエラーは, 概要だけになるか検証."""
        assert "ヒント" not in format_error(_error(401, "UNAUTHENTICATED", "boom"))

    def test_format_error_other(self):
        """Gemini API と無関係な例外は, そのまま文字列になるか検証."""
        assert format_error(ValueError("bad value")) == "bad value"


class TestHttpCode:
    """`_http_code` のテスト."""

    def test_http_code_success(self):
        """整数のステータスコードが返るか検証."""
        assert _http_code(APIError(429, {})) == 429

    def test_http_code_from_text(self):
        """整数でない code (文字列) の場合は, エラー文の先頭の数字から取り出すか検証."""
        assert _http_code(APIError("503 Service Unavailable", {})) == 503

    def test_http_code_unknown(self):
        """取得できない場合は None が返るか検証."""
        assert _http_code(APIError("unknown", {})) is None


class TestQuotaDetail:
    """`_quota_detail` のテスト."""

    def test_quota_detail_success(self):
        """モデル名と上限値が括弧書きで返るか検証."""
        assert (
            _quota_detail("limit: 20, model: gemini-3.8-flash\n")
            == " (モデル: gemini-3.8-flash, 上限: 20 件)"
        )

    def test_quota_detail_empty(self):
        """どちらも含まれていない場合は, 空文字が返るか検証."""
        assert _quota_detail("no info") == ""


class TestRetrySuffix:
    """`_retry_suffix` のテスト."""

    def test_retry_suffix_success(self):
        """推奨待機時間が分かる場合に, 案内文が返るか検証."""
        assert _retry_suffix(MINUTE) == " (約 30 秒後に再試行できます)"

    def test_retry_suffix_empty(self):
        """推奨待機時間が分からない場合は, 空文字が返るか検証."""
        assert _retry_suffix(_error(503, "UNAVAILABLE", "x")) == ""


class TestFirstLine:
    """`_first_line` のテスト."""

    def test_first_line_success(self):
        """メッセージの 1 行目だけが返るか検証."""
        assert _first_line(_error(400, "X", "first\nsecond")) == "first"

    def test_first_line_without_message(self):
        """メッセージが無い場合は, エラー文の文字列表現が使われるか検証."""
        error = APIError(500, {})

        assert _first_line(error) == str(error)
