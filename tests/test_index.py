"""`code_chat_cli.index` モジュールのテスト."""

from unittest.mock import MagicMock, patch

from code_chat_cli.index import handle_ask, handle_index


@patch("code_chat_cli.index.CodeRagService")
def test_handle_index(mock_rag_service_cls):
    """handle_index が CodeRagService を呼び出し, インデックス結果を出力するか検証する."""
    # モックの設定
    mock_service_instance = MagicMock()
    mock_service_instance.index_repository.return_value = 42
    mock_rag_service_cls.return_value = mock_service_instance

    # 実行
    with patch("builtins.print") as mock_print:
        handle_index("/path/to/repo")

    # 検証
    mock_rag_service_cls.assert_called_once_with(persist_directory="./.chroma_db")
    mock_service_instance.index_repository.assert_called_once_with("/path/to/repo")
    mock_print.assert_called_once_with("Index completed: 42 chunks added.")


@patch("code_chat_cli.index.CodeRagService")
def test_handle_ask(mock_rag_service_cls):
    """handle_ask が ask_stream を使ってレスポンスをストリーミング出力するか検証する."""
    # モックの設定
    mock_service_instance = MagicMock()
    mock_service_instance.ask_stream.return_value = iter(["Hello", ", ", "world!"])
    mock_rag_service_cls.return_value = mock_service_instance

    # 実行
    with patch("builtins.print") as mock_print:
        handle_ask("テストの質問")

    # 検証
    mock_rag_service_cls.assert_called_once_with(persist_directory="./.chroma_db")
    mock_service_instance.ask_stream.assert_called_once_with("テストの質問")

    # ストリーミング出力（flush=True）と最後の改行の検証
    assert mock_print.call_count == 4
    mock_print.assert_any_call("Hello", end="", flush=True)
    mock_print.assert_any_call(", ", end="", flush=True)
    mock_print.assert_any_call("world!", end="", flush=True)
    mock_print.assert_called_with()  # 引数なしの print() （改行）
