"""pytest の共通フィクスチャ定義モジュール."""

from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from code_chat_cli.args import CliArgs


@pytest.fixture
def mock_client() -> MagicMock:
    """Gemini API クライアントのモックフィクスチャ."""
    client = MagicMock()
    # 必要に応じてデフォルトの振る舞いを記述
    return client


@pytest.fixture
def mock_args():
    """parse_args の戻り値 (CliArgs と同じ属性) を SimpleNamespace で模したモック."""
    with patch("code_chat_cli.chat.parse_args") as mock_parse:
        args = SimpleNamespace(**asdict(CliArgs(model="gemini-flash-latest")))
        mock_parse.return_value = args
        yield mock_parse


@pytest.fixture
def mock_gemini_client(mock_client):
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


@pytest.fixture
def valid_and_error_files(tmp_path: Path) -> tuple[Path, Path]:
    """同じディレクトリに, 読める `valid.py` と, 読み込みを失敗させる対象の `error.py` を作成する."""
    valid_file = tmp_path / "valid.py"
    valid_file.write_text("print('ok')", encoding="utf-8")

    error_file = tmp_path / "error.py"
    error_file.write_text("print('error')", encoding="utf-8")
    return valid_file, error_file


@pytest.fixture
def fail_read_text():
    """特定のファイル名だけ `Path.read_text` で例外を発生させる patch を作成するファクトリ."""

    def factory(file_name: str, error: Exception):
        original_read_text = Path.read_text

        def read_text(path_obj: Path, *args, **kwargs):
            if path_obj.name == file_name:
                raise error
            return original_read_text(path_obj, *args, **kwargs)

        return patch.object(Path, "read_text", side_effect=read_text, autospec=True)

    return factory
