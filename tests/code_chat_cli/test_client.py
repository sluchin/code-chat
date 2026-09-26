"""`code_chat_cli.client` における API クライアントの初期化, モデルの設定, および通信処理のテスト."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from code_chat_cli.auth import OAuthError
from code_chat_cli.client import ClientConfigError, get_gemini_client


class TestGetGeminiClient:
    """`get_gemini_client` のテスト."""

    def test_get_gemini_client_success(self, monkeypatch):
        """環境変数 GEMINI_API_KEY が設定されている場合, 正常に genai.Client が返されるか検証."""
        # 環境変数をセット
        monkeypatch.setenv("GEMINI_API_KEY", "test-api-key")

        # google.genai.Client のインスタンス化をモック
        with (
            patch("code_chat_cli.client.genai.Client") as mock_client_cls,
            patch("code_chat_cli.client.get_credentials") as get_credentials,
        ):
            mock_instance = MagicMock()
            mock_client_cls.return_value = mock_instance

            client = get_gemini_client()

            # genai.Client が指定の api_key で呼び出され, OAuth は使われないことを検証
            mock_client_cls.assert_called_once_with(api_key="test-api-key")
            get_credentials.assert_not_called()
            assert client == mock_instance

    @pytest.mark.parametrize("interactive", [True, False])
    def test_get_gemini_client_oauth_success(self, monkeypatch, interactive):
        """use_oauth=True の場合, GEMINI_API_KEY が設定されていても OAuth の Bearer トークン付きクライアントが作られるか検証."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-api-key")
        credentials = MagicMock()
        sync_client = httpx.Client()
        async_client = httpx.AsyncClient()

        with (
            patch("code_chat_cli.client.genai.Client") as mock_client_cls,
            patch(
                "code_chat_cli.client.get_credentials", return_value=credentials
            ) as get_credentials,
            patch("code_chat_cli.client.is_interactive", return_value=interactive),
            patch(
                "code_chat_cli.client.build_httpx_clients",
                return_value=(sync_client, async_client),
            ) as build_clients,
        ):
            client = get_gemini_client(use_oauth=True)

        # 対話端末かどうかが渡され, 認証情報から httpx クライアントが作られること
        get_credentials.assert_called_once_with(interactive=interactive)
        build_clients.assert_called_once_with(credentials)
        assert client == mock_client_cls.return_value
        kwargs = mock_client_cls.call_args.kwargs
        # API キーは使われず, ダミーのキーと httpx クライアントが渡されること
        assert kwargs["api_key"] == "oauth-placeholder"
        assert kwargs["http_options"].httpx_client is sync_client
        assert kwargs["http_options"].httpx_async_client is async_client

    def test_get_gemini_client_missing_api_key_failure(self, monkeypatch, capsys):
        """API キーが未設定の場合, OAuth には切り替えず, --oauth を案内して ClientConfigError が発生するか検証."""
        # 環境変数を削除
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

        # 暗黙に OAuth へ切り替わらない (実際のトークンやログインに触れない) ことも検証
        with (
            patch("code_chat_cli.client.get_credentials") as get_credentials,
            pytest.raises(ClientConfigError) as exc_info,
        ):
            get_gemini_client()

        get_credentials.assert_not_called()
        assert "GEMINI_API_KEY" in str(exc_info.value)
        assert "--oauth" in capsys.readouterr().err

    def test_get_gemini_client_oauth_missing_credentials_failure(self, capsys):
        """OAuth の認証情報を取得できない場合, メッセージを表示して ClientConfigError が発生するか検証."""
        with (
            patch(
                "code_chat_cli.client.get_credentials",
                side_effect=OAuthError("OAuth ログインの設定がありません"),
            ),
            patch("code_chat_cli.client.is_interactive", return_value=False),
            pytest.raises(ClientConfigError) as exc_info,
        ):
            get_gemini_client(use_oauth=True)

        assert "OAuth" in str(exc_info.value)
        assert "OAuth ログインの設定がありません" in capsys.readouterr().err
