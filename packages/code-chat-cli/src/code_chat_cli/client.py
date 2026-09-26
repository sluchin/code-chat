"""Gemini CLI Tool - API Client Configuration."""

import os
import sys

from google import genai
from google.genai import types

from code_chat_cli.auth import build_httpx_clients, get_credentials, is_interactive
from code_chat_cli.client_config_error import ClientConfigError
from code_chat_cli.logger import get_logger
from code_chat_cli.oauth_error import OAuthError

logger = get_logger(__name__)

# OAuth 認証時に SDK の API キー必須チェックを通すためのダミー値.
# 実際の送信時に auth.build_httpx_clients がこのキーのヘッダーを外し, Bearer トークンを付与する.
_OAUTH_PLACEHOLDER_API_KEY = "oauth-placeholder"

# リトライは code_chat_cli.api.call_with_retry に一元化している (retryDelay の優先, 1 日あたりの上限の除外,
# 日本語の警告のため). 二重にリトライしないよう, SDK の retry_options は設定しない.


def get_gemini_client(use_oauth: bool = False) -> genai.Client:
    """認証情報から Gemini クライアントを作成する.

    認証方法は `use_oauth` で明示的に選択します (暗黙の切り替えは行いません).

    - `use_oauth=False`: 環境変数 `GEMINI_API_KEY` の API キーを使う
    - `use_oauth=True`: 保存済みの OAuth トークンを使う. トークンがなく対話端末の場合は,
      ブラウザでの OAuth ログインを開始する. `GEMINI_API_KEY` が設定されていても使わない

    Args:
        use_oauth (bool): OAuth で認証するかどうか. Defaults to False.

    Returns:
        genai.Client: 初期化された Gemini API クライアントインスタンス.

    Raises:
        ClientConfigError: 必要な認証情報がなく, ログインも開始できない場合.

    """
    if use_oauth:
        return _get_oauth_client()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("環境変数 GEMINI_API_KEY が設定されていません.")
        print(
            "実行前に export GEMINI_API_KEY='your-api-key' を設定してください.\n"
            "OAuth (Google アカウント) で認証する場合は, --oauth を指定してください"
            " (事前に code-chat --login が必要です).",
            file=sys.stderr,
        )
        raise ClientConfigError("GEMINI_API_KEY is missing")

    return genai.Client(api_key=api_key)


def _get_oauth_client() -> genai.Client:
    """OAuth の認証情報から, Bearer トークンを付与する Gemini クライアントを作成する.

    Returns:
        genai.Client: OAuth 認証済みの Gemini API クライアントインスタンス.

    Raises:
        ClientConfigError: OAuth の設定がない, または未ログインで対話端末ではない場合.

    """
    try:
        credentials = get_credentials(interactive=is_interactive())
    except OAuthError as e:
        logger.error("OAuth の認証情報を取得できませんでした.")
        print(str(e), file=sys.stderr)
        raise ClientConfigError("OAuth credentials are missing") from e

    httpx_client, httpx_async_client = build_httpx_clients(credentials)
    return genai.Client(
        api_key=_OAUTH_PLACEHOLDER_API_KEY,
        http_options=types.HttpOptions(
            httpx_client=httpx_client, httpx_async_client=httpx_async_client
        ),
    )
