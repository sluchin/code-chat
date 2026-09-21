"""pytest の共通フィクスチャ定義モジュール."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_client() -> MagicMock:
    """Gemini API クライアントのモックフィクスチャ."""
    client = MagicMock()
    # 必要に応じてデフォルトの振る舞いを記述
    return client


@pytest.fixture
def mock_args():
    """parse_args の全属性を網羅した SimpleNamespace モック."""
    with patch("code_chat_cli.chat.parse_args") as mock_parse:
        args = SimpleNamespace(
            prompt=None,
            target_path=None,
            output_path=None,
            auto_save=False,
            write_mode=False,
            model="gemini-flash-latest",
            debug=False,
            log_level="INFO",
            list_models=False,
            generate_commit_msg=False,
            review=False,
            staged=False,
            context=None,
            command=None,
            repo_path=".",
            query=None,
            top_k=5,
        )
        mock_parse.return_value = args
        yield mock_parse


@pytest.fixture
def mock_gemini_client():
    """Gemini Client および Chat セッションのモックを作成."""
    with patch("code_chat_cli.chat.get_gemini_client") as mock_get_client:
        mock_chat = MagicMock()

        # ストリーミングレスポンス（イテレータ）のモック
        mock_chunk = MagicMock()
        mock_chunk.text = "モックされたAIからの回答です."
        mock_chat.send_message_stream.return_value = [mock_chunk]

        # 通常送信のレスポンスのモック
        mock_response = MagicMock()
        mock_response.text = "コンテキスト受信完了"
        mock_chat.send_message.return_value = mock_response

        mock_client.chats.create.return_value = mock_chat
        mock_get_client.return_value = mock_client

        yield {
            "get_client": mock_get_client,
            "client": mock_client,
            "chat": mock_chat,
        }
