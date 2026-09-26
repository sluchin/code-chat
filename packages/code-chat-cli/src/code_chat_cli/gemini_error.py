"""Gemini API のエラー (`APIError`) から, ユーザー向けの概要とヒントを作成するモジュール.

`APIError` の文字列表現は, レスポンス全体の辞書を含む長い 1 行になるため, 次の情報を取り出して整理します.

- HTTP ステータスと status (例: `429 RESOURCE_EXHAUSTED`)
- 上限に達した種類 (1 日あたり / 1 分あたり / キャッシュの保存量) とモデル名・上限値
- API が返した推奨待機時間 (`retryDelay`)
"""

import re

from google.genai.errors import APIError

from code_chat_cli.gemini_error_kind import GeminiErrorKind

_MAX_CAUSE_DEPTH = 10
_MAX_MESSAGE_LENGTH = 200


def find_api_error(error: BaseException | None) -> APIError | None:
    """例外 (または, その原因の例外) から, Gemini API のエラーを探します.

    ライブラリが `APIError` を別の例外で包んでいる場合も対象にします.

    Args:
        error (BaseException | None): 調べる例外. `except` ブロックの外では None.

    Returns:
        APIError | None: 見つかった `APIError`. 含まれていない場合は None.

    """
    # 循環参照に備えて, 辿る深さを制限する
    for _ in range(_MAX_CAUSE_DEPTH):
        if error is None:
            return None
        if isinstance(error, APIError):
            return error
        error = error.__cause__ or error.__context__
    return None


def retry_delay_seconds(error: BaseException) -> float | None:
    """API が返した推奨待機時間 (`retryDelay`) を, 秒で取り出します.

    Args:
        error (BaseException): 発生した例外.

    Returns:
        float | None: 推奨待機秒数. 含まれていない場合は None.

    """
    match = re.search(r"retryDelay[\"']?\s*:\s*[\"']?(\d+(?:\.\d+)?)s", str(error))
    return float(match.group(1)) if match else None


def is_daily_quota_error(error: BaseException) -> bool:
    """1 日あたりの上限 (RPD) に達したエラーかどうかを返します.

    1 日あたりの上限は, 待っても回復しないため, リトライの対象になりません.

    Args:
        error (BaseException): 判定対象の例外.

    Returns:
        bool: 1 日あたりの上限に達した場合は True.

    """
    return GeminiErrorKind.QUOTA_PER_DAY in str(error)


def summarize_error(error: APIError) -> str:
    """`APIError` から, 1 行の概要を作成します.

    Args:
        error (APIError): Gemini API のエラー.

    Returns:
        str: `[HTTP 429 RESOURCE_EXHAUSTED] 無料枠の 1 日あたりのリクエスト上限に到達しました ...` の形式の概要.

    """
    code = _http_code(error)
    status = error.status
    if not status and code is not None:
        status = GeminiErrorKind.STATUS_BY_HTTP_CODE.get(code, "")
    label = f" {status}" if status else ""
    return f"[HTTP {code}{label}] {_describe(error)}"


# 原因ごとの分岐を上から順に並べた方が, 表にするより読みやすいため, return の数の制限を外す
# pylint: disable-next=too-many-return-statements
def hint_for_error(error: APIError) -> str | None:
    """`APIError` の原因に応じた, 対処のヒントを作成します.

    Args:
        error (APIError): Gemini API のエラー.

    Returns:
        str | None: 対処のヒント. 該当するものがない場合は None.

    """
    kind = GeminiErrorKind
    text = str(error)
    code = _http_code(error)

    if kind.QUOTA_CACHED_CONTENT_STORAGE in text and kind.TIER_FREE in text:
        return "課金を有効にした有料枠のプロジェクトの API キーを使ってください."
    if code == kind.HTTP_TOO_MANY_REQUESTS and kind.QUOTA_PER_DAY in text:
        return (
            "1 日あたりの上限は, 翌日まで回復しません. "
            "別のモデルを -m で指定するか, 課金を有効にした API キーを使ってください."
        )
    if code == kind.HTTP_TOO_MANY_REQUESTS and kind.QUOTA_PER_MINUTE in text:
        return "しばらく待つと回復します (code-chat は自動でリトライします)."
    if code == kind.HTTP_TOO_MANY_REQUESTS:
        return (
            "原因の候補: (1) 無料枠の上限に到達した, (2) 一度に送るコンテキストが大きすぎる (TPM), "
            "(3) 短時間に連続して呼び出した (RPM)."
        )
    if code == kind.HTTP_SERVICE_UNAVAILABLE:
        return "一時的な混雑です. しばらく待って再実行するか, -m で別のモデルを指定してください."
    if code == kind.HTTP_INTERNAL_SERVER_ERROR:
        return "Google 側の一時的な問題の可能性があります. しばらく待って再実行してください."
    if code == kind.HTTP_GATEWAY_TIMEOUT:
        return "入力が大きすぎる可能性があります. コンテキスト (-f のファイルなど) を減らして再実行してください."
    if code == kind.HTTP_NOT_FOUND:
        return "code-chat --list-models で利用できるモデルを確認し, -m で指定し直してください."
    if code == kind.HTTP_BAD_REQUEST and kind.MESSAGE_API_KEY_INVALID in text:
        return "環境変数 GEMINI_API_KEY の値を確認してください."
    if code == kind.HTTP_BAD_REQUEST and kind.MESSAGE_CACHE_TOO_SMALL in text:
        return "対象のファイルを増やすか, キャッシュを使わずに実行してください."
    if error.status == kind.STATUS_FAILED_PRECONDITION:
        return "Google AI Studio で, 請求先アカウント (課金) の設定を確認してください."
    if kind.REASON_SCOPE_INSUFFICIENT in text:
        return "Context Caching は API キーのみ対応です (--oauth とは併用できません)."
    return None


def format_error(error: BaseException) -> str:
    """例外を, ログに出力する文字列にします. Gemini API のエラーは, 概要とヒントに整理します.

    Args:
        error (BaseException): 発生した例外.

    Returns:
        str: Gemini API のエラーの場合は, 概要 (とヒント). それ以外は, 例外の文字列表現.

    """
    api_error = find_api_error(error)
    if api_error is None:
        return str(error)

    result = summarize_error(api_error)
    hint = hint_for_error(api_error)
    return f"{result}\n  ヒント: {hint}" if hint else result


def _http_code(error: APIError) -> int | None:
    """`APIError` の HTTP ステータスコードを整数で返します (取得できない場合は None)."""
    try:
        return int(error.code)
    except (TypeError, ValueError):
        match = re.match(r"\d+", str(error))
        return int(match.group()) if match else None


def _quota_detail(text: str) -> str:
    """エラー文から, 上限に達したモデル名と上限値を取り出し, 括弧書きにします."""
    parts = []
    model = re.search(r"model: ([\w.\-]+)", text)
    limit = re.search(r"limit: (\d+)", text)
    if model:
        parts.append(f"モデル: {model.group(1)}")
    if limit:
        parts.append(f"上限: {limit.group(1)} 件")
    return f" ({', '.join(parts)})" if parts else ""


def _retry_suffix(error: APIError) -> str:
    """推奨待機時間が分かる場合の, 案内文を返します."""
    seconds = retry_delay_seconds(error)
    return f" (約 {round(seconds)} 秒後に再試行できます)" if seconds else ""


def _first_line(error: APIError) -> str:
    """エラーメッセージの 1 行目を, 長さを制限して返します."""
    message = (error.message or str(error)).strip().split("\n")[0]
    return message[:_MAX_MESSAGE_LENGTH]


# 原因ごとの分岐を上から順に並べた方が, 表にするより読みやすいため, return の数の制限を外す
# pylint: disable-next=too-many-return-statements
def _describe(error: APIError) -> str:
    """`APIError` の内容を, 日本語の 1 文にします."""
    kind = GeminiErrorKind
    text = str(error)
    code = _http_code(error)

    if kind.QUOTA_CACHED_CONTENT_STORAGE in text and kind.TIER_FREE in text:
        return "無料枠では Context Caching を利用できません (キャッシュの保存量の上限が 0 のため)"
    if code == kind.HTTP_TOO_MANY_REQUESTS and kind.QUOTA_PER_DAY in text:
        tier = "無料枠の " if kind.TIER_FREE in text else ""
        return f"{tier}1 日あたりのリクエスト上限に到達しました{_quota_detail(text)}"
    if code == kind.HTTP_TOO_MANY_REQUESTS and kind.QUOTA_PER_MINUTE in text:
        return f"1 分あたりのリクエスト上限に到達しました{_quota_detail(text)}{_retry_suffix(error)}"
    if code == kind.HTTP_TOO_MANY_REQUESTS:
        return (
            f"リクエストの上限に到達しました{_quota_detail(text)}{_retry_suffix(error)}"
        )
    if code == kind.HTTP_SERVICE_UNAVAILABLE:
        return f"モデルが高負荷で, 一時的に利用できません{_retry_suffix(error)}"
    if code == kind.HTTP_INTERNAL_SERVER_ERROR:
        return "Google 側で内部エラーが発生しました"
    if code == kind.HTTP_GATEWAY_TIMEOUT:
        return "処理が制限時間内に終わりませんでした (タイムアウト)"
    if code == kind.HTTP_NOT_FOUND:
        return f"指定したモデルまたはリソースが見つかりません: {_first_line(error)}"
    if code == kind.HTTP_BAD_REQUEST and kind.MESSAGE_API_KEY_INVALID in text:
        return "API キーが無効です"
    if code == kind.HTTP_BAD_REQUEST and kind.MESSAGE_CACHE_TOO_SMALL in text:
        minimum = re.search(r"min_total_token_count=(\d+)", text)
        detail = f" (最小 {minimum.group(1)} トークン)" if minimum else ""
        return f"キャッシュ対象のコンテキストが小さすぎます{detail}"
    if error.status == kind.STATUS_FAILED_PRECONDITION:
        return (
            "この地域では, 課金の設定なしに利用できません (前提条件を満たしていません)"
        )
    if kind.REASON_SCOPE_INSUFFICIENT in text:
        return "OAuth のトークンのスコープが不足しています"
    return _first_line(error)
