"""`code_chat_cli.auth` モジュールのテスト."""

import asyncio
import datetime
import json
import stat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest
from code_chat_cli.auth import (
    CLIENT_ID_ENV,
    CLIENT_SECRET_ENV,
    SCOPES,
    OAuthError,
    build_httpx_clients,
    get_credentials,
    get_token_path,
    is_interactive,
    load_credentials,
    login,
    save_credentials,
)
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials


def _utcnow() -> datetime.datetime:
    """google-auth が扱う naive な UTC 現在時刻を返す."""
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def _credentials(**overrides) -> Credentials:
    """テスト用の OAuth 認証情報を作成する (外部通信は行わない).

    有効期限が無いと, 保存・再読み込み時に期限切れ扱いとなりリフレッシュ (外部通信) が
    発生するため, 既定で 1 時間後の有効期限を持たせる.
    """
    params = {
        "expiry": _utcnow() + datetime.timedelta(hours=1),
        "token": "access-token",
        "refresh_token": "refresh-token",
        "client_id": "client-id",
        "client_secret": "client-secret",
        "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": SCOPES,
    }
    params.update(overrides)
    return Credentials(**params)


def _expired_credentials() -> Credentials:
    """期限切れの認証情報を作成する."""
    return _credentials(expiry=_utcnow() - datetime.timedelta(hours=1))


class TestGetTokenPath:
    """`get_token_path` のテスト."""

    def test_get_token_path_success(self, monkeypatch, tmp_path):
        """トークンの保存先がホーム配下の ~/.config/code-chat/oauth_token.json になるか検証."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        assert (
            get_token_path() == tmp_path / ".config" / "code-chat" / "oauth_token.json"
        )


class TestSaveCredentials:
    """`save_credentials` のテスト."""

    def test_save_credentials_success(self, tmp_path):
        """親ディレクトリが作成され, 所有者のみ読み書き可能なファイルで保存されるか検証."""
        path = tmp_path / "nested" / "oauth_token.json"

        result = save_credentials(_credentials(), path)

        assert result == path
        assert json.loads(path.read_text(encoding="utf-8"))["refresh_token"] == (
            "refresh-token"
        )
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_save_credentials_overwrites_permissions_success(self, tmp_path):
        """既存ファイルの権限が緩くても, 保存後は 0600 になるか検証."""
        path = tmp_path / "oauth_token.json"
        path.write_text("{}", encoding="utf-8")
        path.chmod(0o644)

        save_credentials(_credentials(), path)

        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_save_credentials_default_path_success(self, monkeypatch, tmp_path):
        """保存先を省略した場合は既定のパスに保存されるか検証."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        result = save_credentials(_credentials())

        assert result == get_token_path()
        assert result.is_file()


class TestLoadCredentials:
    """`load_credentials` のテスト."""

    def test_load_credentials_success(self, tmp_path):
        """保存済みの有効なトークンが読み込まれるか検証."""
        path = tmp_path / "oauth_token.json"
        save_credentials(_credentials(), path)

        result = load_credentials(path)

        assert result is not None
        assert result.token == "access-token"
        assert result.refresh_token == "refresh-token"

    def test_load_credentials_refreshes_expired_success(self, tmp_path):
        """期限切れのトークンがリフレッシュされ, 保存し直されるか検証."""
        path = tmp_path / "oauth_token.json"
        save_credentials(_expired_credentials(), path)

        def fake_refresh(credentials, _request):
            credentials.token = "new-token"
            credentials.expiry = None

        with patch.object(
            Credentials, "refresh", autospec=True, side_effect=fake_refresh
        ) as refresh:
            result = load_credentials(path)

        refresh.assert_called_once()
        assert result is not None
        assert result.token == "new-token"
        assert json.loads(path.read_text(encoding="utf-8"))["token"] == "new-token"

    def test_load_credentials_invalid_file_failure(self, tmp_path, caplog):
        """トークンファイルが壊れている場合は, 警告を出して None を返すか検証."""
        path = tmp_path / "oauth_token.json"
        path.write_text("not json", encoding="utf-8")

        assert load_credentials(path) is None
        assert "読み込めませんでした" in caplog.text

    def test_load_credentials_refresh_error_exception(self, tmp_path, caplog):
        """リフレッシュトークンが失効している場合は, 警告を出して None を返すか検証."""
        path = tmp_path / "oauth_token.json"
        save_credentials(_expired_credentials(), path)

        with patch.object(
            Credentials, "refresh", side_effect=RefreshError("invalid_grant")
        ):
            result = load_credentials(path)

        assert result is None
        assert "再ログインが必要です" in caplog.text

    def test_load_credentials_missing_file(self, tmp_path):
        """トークンファイルが存在しない場合は None を返すか検証."""
        assert load_credentials(tmp_path / "missing.json") is None


class TestLogin:
    """`login` のテスト."""

    def test_login_success(self, monkeypatch, tmp_path):
        """環境変数のクライアント情報で認証フローが実行され, トークンが保存されるか検証."""
        monkeypatch.setenv(CLIENT_ID_ENV, "env-client-id")
        monkeypatch.setenv(CLIENT_SECRET_ENV, "env-client-secret")
        path = tmp_path / "oauth_token.json"
        credentials = _credentials()

        with patch("code_chat_cli.auth.InstalledAppFlow") as flow_cls:
            flow_cls.from_client_config.return_value.run_local_server.return_value = (
                credentials
            )
            result = login(path)

        assert result is credentials
        config, scopes = flow_cls.from_client_config.call_args.args
        assert config["installed"]["client_id"] == "env-client-id"
        assert config["installed"]["client_secret"] == "env-client-secret"
        assert scopes == SCOPES
        flow_cls.from_client_config.return_value.run_local_server.assert_called_once_with(
            port=0, prompt="consent"
        )
        assert path.is_file()

    @pytest.mark.parametrize(
        ("client_id", "client_secret"),
        [(None, None), ("id-only", None), (None, "secret-only")],
    )
    def test_login_missing_env_failure(
        self, monkeypatch, tmp_path, client_id, client_secret
    ):
        """クライアント ID / シークレットのいずれかが未設定の場合, 設定方法を示す OAuthError が発生するか検証."""
        monkeypatch.delenv(CLIENT_ID_ENV, raising=False)
        monkeypatch.delenv(CLIENT_SECRET_ENV, raising=False)
        if client_id:
            monkeypatch.setenv(CLIENT_ID_ENV, client_id)
        if client_secret:
            monkeypatch.setenv(CLIENT_SECRET_ENV, client_secret)

        with patch("code_chat_cli.auth.InstalledAppFlow") as flow_cls:
            with pytest.raises(OAuthError, match=CLIENT_ID_ENV):
                login(tmp_path / "oauth_token.json")

        flow_cls.from_client_config.assert_not_called()


class TestGetCredentials:
    """`get_credentials` のテスト."""

    def test_get_credentials_saved_token_success(self):
        """保存済みのトークンがあれば, ログインせずにそれを返すか検証."""
        credentials = _credentials()

        with (
            patch("code_chat_cli.auth.load_credentials", return_value=credentials),
            patch("code_chat_cli.auth.login") as login_mock,
        ):
            result = get_credentials(interactive=True)

        assert result is credentials
        login_mock.assert_not_called()

    def test_get_credentials_interactive_login_success(self):
        """トークンが無く対話端末の場合は, ログインを開始してその結果を返すか検証."""
        credentials = _credentials()

        with (
            patch("code_chat_cli.auth.load_credentials", return_value=None),
            patch("code_chat_cli.auth.login", return_value=credentials) as login_mock,
        ):
            result = get_credentials(interactive=True)

        assert result is credentials
        login_mock.assert_called_once_with()

    def test_get_credentials_not_logged_in_failure(self, monkeypatch):
        """非対話環境でトークンが無い場合は, --login の実行を促す OAuthError が発生するか検証."""
        monkeypatch.setenv(CLIENT_ID_ENV, "id")
        monkeypatch.setenv(CLIENT_SECRET_ENV, "secret")

        with (
            patch("code_chat_cli.auth.load_credentials", return_value=None),
            patch("code_chat_cli.auth.login") as login_mock,
            pytest.raises(OAuthError, match="--login"),
        ):
            get_credentials(interactive=False)

        login_mock.assert_not_called()

    def test_get_credentials_not_configured_failure(self, monkeypatch):
        """非対話環境でクライアント情報も無い場合は, 設定方法を示す OAuthError が発生するか検証."""
        monkeypatch.delenv(CLIENT_ID_ENV, raising=False)
        monkeypatch.delenv(CLIENT_SECRET_ENV, raising=False)

        with (
            patch("code_chat_cli.auth.load_credentials", return_value=None),
            pytest.raises(OAuthError, match=CLIENT_SECRET_ENV),
        ):
            get_credentials(interactive=False)


class TestBuildHttpxClients:
    """`build_httpx_clients` のテスト."""

    def test_build_httpx_clients_success(self):
        """API キーのヘッダーが外され, Bearer トークンが付与されるか検証."""
        client, async_client = build_httpx_clients(_credentials())
        request = httpx.Request(
            "POST",
            "https://generativelanguage.googleapis.com/v1beta/models",
            headers={"x-goog-api-key": "oauth-placeholder"},
        )

        client.event_hooks["request"][0](request)
        client.close()

        assert "x-goog-api-key" not in request.headers
        assert request.headers["Authorization"] == "Bearer access-token"
        asyncio.run(async_client.aclose())

    def test_build_httpx_clients_async_success(self):
        """非同期クライアントでも Bearer トークンが付与されるか検証."""
        client, async_client = build_httpx_clients(_credentials())
        request = httpx.Request(
            "POST",
            "https://generativelanguage.googleapis.com/v1beta/models",
            headers={"x-goog-api-key": "oauth-placeholder"},
        )

        asyncio.run(async_client.event_hooks["request"][0](request))
        client.close()
        asyncio.run(async_client.aclose())

        assert "x-goog-api-key" not in request.headers
        assert request.headers["Authorization"] == "Bearer access-token"

    def test_build_httpx_clients_refreshes_expired_token_success(self, tmp_path):
        """期限切れの場合はリフレッシュされ, 更新後のトークンが付与・保存されるか検証."""
        credentials = MagicMock()
        credentials.valid = False
        credentials.token = "old-token"

        def fake_refresh(_request):
            credentials.token = "new-token"

        credentials.refresh.side_effect = fake_refresh
        path = tmp_path / "oauth_token.json"
        client, async_client = build_httpx_clients(credentials, path)
        request = httpx.Request("POST", "https://generativelanguage.googleapis.com/")

        with patch("code_chat_cli.auth.save_credentials") as save:
            client.event_hooks["request"][0](request)
        client.close()
        asyncio.run(async_client.aclose())

        credentials.refresh.assert_called_once()
        save.assert_called_once_with(credentials, path)
        assert request.headers["Authorization"] == "Bearer new-token"

    def test_build_httpx_clients_refresh_error_failure(self):
        """リフレッシュに失敗した場合は, 再ログインを促す OAuthError が発生するか検証."""
        credentials = MagicMock()
        credentials.valid = False
        credentials.refresh.side_effect = RefreshError("invalid_grant")
        client, async_client = build_httpx_clients(credentials)
        request = httpx.Request("POST", "https://generativelanguage.googleapis.com/")

        with pytest.raises(OAuthError, match="--login"):
            client.event_hooks["request"][0](request)

        client.close()
        asyncio.run(async_client.aclose())


class TestIsInteractive:
    """`is_interactive` のテスト."""

    @pytest.mark.parametrize("is_tty", [True, False])
    def test_is_interactive_success(self, monkeypatch, is_tty):
        """標準入力が端末かどうかがそのまま返るか検証."""
        monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: is_tty))

        assert is_interactive() is is_tty
