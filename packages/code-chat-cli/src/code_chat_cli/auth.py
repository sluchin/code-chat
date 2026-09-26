"""Gemini API の OAuth 認証 (ログイン・トークン管理・リクエストへの認証付与) を扱うモジュール.

OAuth クライアントの ID とシークレットは, 環境変数 `GEMINI_OAUTH_CLIENT_ID` /
`GEMINI_OAUTH_CLIENT_SECRET` から取得します (リポジトリやツール内には保持しません).
取得したトークンは `~/.config/code-chat/oauth_token.json` に保存し, 期限切れ時は
リフレッシュトークンで自動更新します.
"""

import os
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from code_chat_cli.logger import get_logger
from code_chat_cli.oauth_error import OAuthError

logger = get_logger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/generative-language.retriever",
]
CLIENT_ID_ENV = "GEMINI_OAUTH_CLIENT_ID"
CLIENT_SECRET_ENV = "GEMINI_OAUTH_CLIENT_SECRET"

_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
_TOKEN_URI = "https://oauth2.googleapis.com/token"

SETUP_MESSAGE = f"""OAuth ログインの設定がありません. 次の手順で設定してください.
  1. Google Cloud コンソールで OAuth クライアント ID (種類: デスクトップアプリ) を作成する
  2. 環境変数を設定する
       export {CLIENT_ID_ENV}='your-client-id.apps.googleusercontent.com'
       export {CLIENT_SECRET_ENV}='your-client-secret'
  3. code-chat --login を実行する (以降は --oauth を付けて code-chat を実行する)
API キーを使う場合は, export GEMINI_API_KEY='your-api-key' を設定してください."""


def get_token_path() -> Path:
    """OAuth トークンの保存先パスを返す.

    Returns:
        Path: `~/.config/code-chat/oauth_token.json`.

    """
    return Path.home() / ".config" / "code-chat" / "oauth_token.json"


def save_credentials(credentials: Credentials, token_path: Path | None = None) -> Path:
    """認証情報を所有者のみ読み書き可能なファイルとして保存する.

    Args:
        credentials (Credentials): 保存する認証情報.
        token_path (Path | None): 保存先. 省略時は既定のパス.

    Returns:
        Path: 保存したファイルのパス.

    """
    path = token_path or get_token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(credentials.to_json())
    path.chmod(0o600)
    return path


def load_credentials(token_path: Path | None = None) -> Credentials | None:
    """保存済みの認証情報を読み込み, 期限切れならリフレッシュして返す.

    Args:
        token_path (Path | None): 読み込み元. 省略時は既定のパス.

    Returns:
        Credentials | None: 有効な認証情報. 未保存・破損・失効の場合は None.

    """
    path = token_path or get_token_path()
    if not path.is_file():
        return None

    try:
        credentials = Credentials.from_authorized_user_file(str(path), SCOPES)
    except (ValueError, KeyError):
        logger.warning("保存済みのトークンを読み込めませんでした: %s", path)
        return None

    if not credentials.valid:
        try:
            credentials.refresh(Request())
        except RefreshError as e:
            logger.warning("トークンの更新に失敗しました. 再ログインが必要です: %s", e)
            return None
        save_credentials(credentials, path)

    return credentials


def login(token_path: Path | None = None) -> Credentials:
    """ブラウザで OAuth 認証を行い, トークンを保存する.

    Args:
        token_path (Path | None): 保存先. 省略時は既定のパス.

    Returns:
        Credentials: 認証済みの認証情報.

    Raises:
        OAuthError: クライアント ID / シークレットの環境変数が未設定の場合.

    """
    client_id = os.getenv(CLIENT_ID_ENV)
    client_secret = os.getenv(CLIENT_SECRET_ENV)
    if not client_id or not client_secret:
        raise OAuthError(SETUP_MESSAGE)

    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": _AUTH_URI,
                "token_uri": _TOKEN_URI,
                "redirect_uris": ["http://localhost"],
            }
        },
        SCOPES,
    )
    # prompt="consent" で, 再ログイン時にもリフレッシュトークンを確実に受け取る
    credentials = flow.run_local_server(port=0, prompt="consent")

    path = save_credentials(credentials, token_path)
    logger.info("OAuth トークンを保存しました: %s", path)
    return credentials  # type: ignore[no-any-return]


def get_credentials(interactive: bool) -> Credentials:
    """保存済みの認証情報を返す. 無ければ, 対話端末に限りログインを開始する.

    Args:
        interactive (bool): 対話端末かどうか. True の場合, 未ログインならログインを開始する.

    Returns:
        Credentials: 有効な認証情報.

    Raises:
        OAuthError: 設定がない場合, または非対話環境で未ログインの場合.

    """
    credentials = load_credentials()
    if credentials is not None:
        return credentials

    if interactive:
        logger.info("OAuth ログインが必要です. ブラウザで認証してください")
        return login()

    if not os.getenv(CLIENT_ID_ENV) or not os.getenv(CLIENT_SECRET_ENV):
        raise OAuthError(SETUP_MESSAGE)
    raise OAuthError("OAuth ログインが必要です. code-chat --login を実行してください.")


def build_httpx_clients(
    credentials: Credentials, token_path: Path | None = None
) -> tuple[httpx.Client, httpx.AsyncClient]:
    """リクエストに OAuth の Bearer トークンを付与する httpx クライアントを作成する.

    google-genai の Gemini API クライアントは API キーを必須とし OAuth 認証情報を直接
    受け付けないため, 送信直前に API キーのヘッダーを外して Bearer トークンを付与する.
    トークンは期限切れ時に自動で更新される.

    Args:
        credentials (Credentials): 認証済みの認証情報.
        token_path (Path | None): 更新したトークンの保存先. 省略時は既定のパス.

    Returns:
        tuple[httpx.Client, httpx.AsyncClient]: 同期用と非同期用の httpx クライアント.

    """

    def apply_bearer(request: httpx.Request) -> None:
        if not credentials.valid:
            try:
                credentials.refresh(Request())
            except RefreshError as e:
                raise OAuthError(
                    "OAuth トークンの更新に失敗しました. code-chat --login で再ログインしてください."
                ) from e
            save_credentials(credentials, token_path)
        request.headers.pop("x-goog-api-key", None)
        request.headers["Authorization"] = f"Bearer {credentials.token}"

    async def apply_bearer_async(request: httpx.Request) -> None:
        apply_bearer(request)

    sync_hooks: list[Callable[[httpx.Request], None]] = [apply_bearer]
    async_hooks: list[Callable[[httpx.Request], Awaitable[None]]] = [apply_bearer_async]
    return (
        httpx.Client(event_hooks={"request": sync_hooks}),
        httpx.AsyncClient(event_hooks={"request": async_hooks}),
    )


def is_interactive() -> bool:
    """標準入力が端末に接続されているか (ブラウザでのログインを開始してよいか) を返す."""
    return sys.stdin.isatty()
