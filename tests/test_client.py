from unittest.mock import MagicMock, patch

import pytest

from code_chat.client import get_gemini_client


def test_get_gemini_client_success(monkeypatch):
    """環境変数 GEMINI_API_KEY が設定されている場合、正常に genai.Client が返されるか検証."""
    # 環境変数をセット
    monkeypatch.setenv("GEMINI_API_KEY", "test-api-key")

    # google.genai.Client のインスタンス化をモック
    with patch("code_chat.client.genai.Client") as mock_client_cls:
        mock_instance = MagicMock()
        mock_client_cls.return_value = mock_instance

        client = get_gemini_client()

        # genai.Client が指定の api_key で呼び出されたか検証
        mock_client_cls.assert_called_once_with(api_key="test-api-key")
        assert client == mock_instance


def test_get_gemini_client_missing_api_key(monkeypatch, capsys):
    """環境変数 GEMINI_API_KEY が未設定の場合、エラーメッセージを出力して sys.exit(1) で終了するか検証."""
    # 環境変数を削除
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    # sys.exit(1) が発生することを確認
    with pytest.raises(SystemExit) as exc_info:
        get_gemini_client()

    assert exc_info.value.code == 1

    # stderr に期待する案内メッセージが出力されたか検証
    captured = capsys.readouterr()
    assert "export GEMINI_API_KEY='your-api-key'" in captured.err
