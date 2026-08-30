# pylint: disable=redefined-outer-name
"""モデル一覧の取得および表示処理を行うサブコマンドモジュール."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from code_chat_cli.chat import (
    main,
)
from code_chat_cli.commands.models import handle_list_models


@pytest.fixture
def mock_gemini_client():
    """Gemini Client および Chat セッションのモックを作成."""
    with patch("code_chat_cli.chat.get_gemini_client") as mock_get_client:
        mock_client = MagicMock()
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
def mock_args():
    """parse_args の全属性を網羅した SimpleNamespace モック."""
    with patch("code_chat_cli.chat.parse_args") as mock_parse:
        args = SimpleNamespace(
            debug=False,
            log_level="INFO",
            write_mode=False,
            model="gemini-flash-latest",
            context=None,
            prompt=None,
            output_path=None,
            target_path=None,
            auto_save=False,
            list_models=False,
            generate_commit_msg=False,
            review=False,
            staged=False,
        )
        mock_parse.return_value = args
        yield mock_parse


def test_main_list_models_option(monkeypatch, mock_gemini_client, mock_args, capsys):
    """--list-models 指定時にモデル一覧を表示して正常終了するか検証."""
    mock_args.return_value.list_models = True

    # モデルのモックを作成（SimpleNamespace を使用）
    mock_model = SimpleNamespace(
        name="models/gemini-flash-latest",
        display_name="Gemini Flash Latest",
        supported_actions=["generateContent"],
        supported_generation_methods=["generateContent"],
    )

    # models.list() の戻り値としてモックのリストを設定
    mock_gemini_client["client"].models.list.return_value = [mock_model]

    monkeypatch.setattr("sys.argv", ["chat.py", "--list-models"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    captured = capsys.readouterr()

    # 期待するモデル名が出力に含まれているか検証
    assert "- gemini-flash-latest (Gemini Flash Latest)" in captured.out


def test_main_list_models_exception(monkeypatch, mock_gemini_client, mock_args):
    """--list-models 指定時に API エラー等の例外が発生した場合, sys.exit(1) で終了するか検証."""
    mock_args.return_value.list_models = True

    # models.list() 呼び出し時に Exception を発生させる
    mock_gemini_client["client"].models.list.side_effect = Exception(
        "API connection error"
    )

    monkeypatch.setattr("sys.argv", ["chat.py", "--list-models"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    # ステータスコード 1 で終了したことを検証
    assert exc_info.value.code == 1


def test_handle_list_models_exception(mock_client: MagicMock) -> None:
    """model.list() で例外が発生した場合、例外がログ出力されて再送出されることを検証する."""
    # client.models.list() が例外を発生させるようにモックを設定
    mock_client.models.list.side_effect = Exception("API Error")

    with pytest.raises(Exception, match="API Error"):
        handle_list_models(mock_client)

    # 18-20行目の try-except ブロックが確実に通過されたことを検証
    mock_client.models.list.assert_called_once()
