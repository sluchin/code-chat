"""Gemini API のエラー種別 (HTTP ステータス, status, 原因の判別に使う文字列) を定義するモジュール."""

from types import MappingProxyType


class GeminiErrorKind:
    """Gemini API のエラー種別を, クラス属性として保持するクラス.

    エラーの判別に使う値 (HTTP ステータス, status, quotaId やメッセージに含まれる文字列) を,
    コード中に直接書かずに, ここで一元管理します.
    """

    # HTTP ステータスコード
    HTTP_BAD_REQUEST = 400
    """リクエストの内容が不正 (API キーが無効, 引数が不正, 前提条件を満たさない, など)."""

    HTTP_FORBIDDEN = 403
    """権限がない (OAuth のスコープ不足など)."""

    HTTP_NOT_FOUND = 404
    """モデルやリソースが見つからない (モデルの提供終了を含む)."""

    HTTP_TOO_MANY_REQUESTS = 429
    """上限に到達した (1 日あたり / 1 分あたり / キャッシュの保存量)."""

    HTTP_INTERNAL_SERVER_ERROR = 500
    """Google 側の内部エラー."""

    HTTP_SERVICE_UNAVAILABLE = 503
    """モデルが高負荷で, 一時的に利用できない."""

    HTTP_GATEWAY_TIMEOUT = 504
    """処理が制限時間内に終わらなかった."""

    # status (Google API のエラーコード名)
    STATUS_INVALID_ARGUMENT = "INVALID_ARGUMENT"
    STATUS_FAILED_PRECONDITION = "FAILED_PRECONDITION"
    STATUS_PERMISSION_DENIED = "PERMISSION_DENIED"
    STATUS_NOT_FOUND = "NOT_FOUND"
    STATUS_RESOURCE_EXHAUSTED = "RESOURCE_EXHAUSTED"
    STATUS_INTERNAL = "INTERNAL"
    STATUS_UNAVAILABLE = "UNAVAILABLE"
    STATUS_DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"

    STATUS_BY_HTTP_CODE = MappingProxyType(
        {
            HTTP_BAD_REQUEST: STATUS_INVALID_ARGUMENT,
            HTTP_FORBIDDEN: STATUS_PERMISSION_DENIED,
            HTTP_NOT_FOUND: STATUS_NOT_FOUND,
            HTTP_TOO_MANY_REQUESTS: STATUS_RESOURCE_EXHAUSTED,
            HTTP_INTERNAL_SERVER_ERROR: STATUS_INTERNAL,
            HTTP_SERVICE_UNAVAILABLE: STATUS_UNAVAILABLE,
            HTTP_GATEWAY_TIMEOUT: STATUS_DEADLINE_EXCEEDED,
        }
    )
    """レスポンスに status が含まれない場合に, HTTP ステータスから補う status."""

    # 429 の原因を判別する文字列 (quotaId に含まれる)
    QUOTA_PER_DAY = "PerDay"
    """1 日あたりのリクエスト上限 (RPD). 待っても回復しない."""

    QUOTA_PER_MINUTE = "PerMinute"
    """1 分あたりのリクエスト上限 (RPM). しばらく待つと回復する."""

    QUOTA_CACHED_CONTENT_STORAGE = "CachedContentStorage"
    """Context Caching で保存できるトークン量の上限."""

    TIER_FREE = "FreeTier"
    """無料枠の上限."""

    # エラーメッセージ・理由に含まれる文字列
    MESSAGE_API_KEY_INVALID = "API key not valid"
    """API キーが無効 (400)."""

    MESSAGE_CACHE_TOO_SMALL = "too small"
    """キャッシュ対象のコンテキストが小さすぎる (400)."""

    REASON_SCOPE_INSUFFICIENT = "ACCESS_TOKEN_SCOPE_INSUFFICIENT"
    """OAuth のトークンのスコープが不足している (403)."""

    # リトライの対象
    RETRYABLE_HTTP_CODES = (HTTP_SERVICE_UNAVAILABLE, HTTP_TOO_MANY_REQUESTS)
    """一時的なエラーとして, リトライの対象にする HTTP ステータス."""

    RETRYABLE_KEYWORDS = (
        str(HTTP_SERVICE_UNAVAILABLE),
        STATUS_UNAVAILABLE,
        str(HTTP_TOO_MANY_REQUESTS),
        STATUS_RESOURCE_EXHAUSTED,
    )
    """HTTP ステータスが取得できない場合に, エラー文から一時的なエラーを判別するキーワード."""
