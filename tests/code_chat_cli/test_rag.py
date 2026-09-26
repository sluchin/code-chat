"""`code_chat_cli.rag` モジュールのテスト."""

from unittest.mock import MagicMock, patch

import pytest

from code_chat_cli.rag import (
    handle_rag,
    handle_rag_create,
    handle_rag_rm,
    handle_rag_status,
    handle_rag_update,
)


class TestHandleRagCreate:
    """`handle_rag_create` のテスト."""

    @patch("code_chat_cli.rag.RagService")
    def test_handle_rag_create_success(self, mock_rag_service_cls):
        """handle_rag_create がインデックスを作成し, 結果を出力するか検証する."""
        mock_service = MagicMock()
        mock_service.index_repository.return_value = 42
        mock_rag_service_cls.return_value = mock_service

        with patch("builtins.print") as mock_print:
            handle_rag_create(["/path/to/repo"], "./.chroma_db")

        mock_rag_service_cls.assert_called_once_with(output_dir="./.chroma_db")
        mock_service.index_repository.assert_called_once_with(["/path/to/repo"])
        assert "42 チャンク追加" in mock_print.call_args[0][0]

    @patch("code_chat_cli.rag.RagService")
    def test_handle_rag_create_error_failure(self, mock_rag_service_cls):
        """インデックス作成で例外が発生した場合は, 握りつぶさずに, 呼び出し元へ送出されるか検証する."""
        mock_rag_service_cls.return_value.index_repository.side_effect = RuntimeError(
            "x"
        )

        with pytest.raises(RuntimeError, match="x"):
            handle_rag_create(["/path/to/repo"])

    @patch("code_chat_cli.rag.Indexer")
    @patch("code_chat_cli.rag.RagService")
    def test_handle_rag_create_dryrun(self, mock_rag_service_cls, mock_indexer_cls):
        """dryrun=True の場合は対象ファイルを表示するだけで, インデックスを作成しないか検証する."""
        mock_indexer_cls.return_value.get_target_files.return_value = ["a.py", "b.py"]

        with patch("builtins.print") as mock_print:
            handle_rag_create(["/path/to/repo"], dryrun=True)

        mock_rag_service_cls.assert_not_called()
        mock_print.assert_any_call("a.py")
        mock_print.assert_any_call("対象ファイル数: 2")


class TestHandleRagUpdate:
    """`handle_rag_update` のテスト."""

    @patch("code_chat_cli.rag.RagService")
    def test_handle_rag_update_success(self, mock_rag_service_cls):
        """handle_rag_update が差分更新モード (update_only=True) で呼び出されるか検証する."""
        mock_service = MagicMock()
        mock_service.index_repository.return_value = 3
        mock_rag_service_cls.return_value = mock_service

        with patch("builtins.print"):
            handle_rag_update(["/path/to/repo"], "./.chroma_db")

        mock_service.index_repository.assert_called_once_with(
            ["/path/to/repo"], update_only=True
        )

    @patch("code_chat_cli.rag.RagService")
    def test_handle_rag_update_error_failure(self, mock_rag_service_cls):
        """差分更新で例外が発生した場合は, 握りつぶさずに, 呼び出し元へ送出されるか検証する."""
        mock_rag_service_cls.return_value.index_repository.side_effect = RuntimeError(
            "x"
        )

        with pytest.raises(RuntimeError, match="x"):
            handle_rag_update(["/path/to/repo"])

    @patch("code_chat_cli.rag.Indexer")
    @patch("code_chat_cli.rag.RagService")
    def test_handle_rag_update_dryrun(self, mock_rag_service_cls, mock_indexer_cls):
        """dryrun=True の場合は対象ファイルを表示するだけで更新しないか検証する."""
        mock_indexer_cls.return_value.get_target_files.return_value = ["a.py"]

        with patch("builtins.print") as mock_print:
            handle_rag_update(["/path/to/repo"], dryrun=True)

        mock_rag_service_cls.assert_not_called()
        mock_print.assert_any_call("対象ファイル数: 1")


class TestHandleRagRm:
    """`handle_rag_rm` のテスト."""

    @patch("code_chat_cli.rag.RagService")
    def test_handle_rag_rm_success(self, mock_rag_service_cls):
        """handle_rag_rm がベクトルストアを初期化するか検証する."""
        handle_rag_rm("./.chroma_db")

        mock_rag_service_cls.assert_called_once_with(output_dir="./.chroma_db")
        mock_rag_service_cls.return_value.clear.assert_called_once_with()

    @patch("code_chat_cli.rag.RagService")
    def test_handle_rag_rm_error_failure(self, mock_rag_service_cls):
        """削除で例外が発生した場合は, 握りつぶさずに, 呼び出し元へ送出されるか検証する."""
        mock_rag_service_cls.return_value.clear.side_effect = RuntimeError("x")

        with pytest.raises(RuntimeError, match="x"):
            handle_rag_rm()


class TestHandleRagStatus:
    """`handle_rag_status` のテスト."""

    @patch("code_chat_cli.rag.RagService")
    def test_handle_rag_status_success(self, mock_rag_service_cls):
        """ステータス情報が出力されるか検証する."""
        mock_rag_service_cls.return_value.get_status.return_value = "STATUS"

        with patch("builtins.print") as mock_print:
            handle_rag_status(["."], "./.chroma_db")

        mock_rag_service_cls.assert_called_once_with(
            input_dirs=["."], output_dir="./.chroma_db"
        )
        mock_print.assert_called_once_with("--- [RAG Index Status] ---\nSTATUS")


class TestHandleRag:
    """`handle_rag` のテスト."""

    @patch("code_chat_cli.rag.RagService")
    def test_handle_rag_success(self, mock_rag_service_cls):
        """handle_rag が query_stream の結果をストリーミング出力するか検証する."""
        mock_service = MagicMock()
        mock_service.query_stream.return_value = iter(["Hello", ", ", "world!"])
        mock_rag_service_cls.return_value = mock_service

        with patch("builtins.print") as mock_print:
            handle_rag("テストの質問")

        mock_rag_service_cls.assert_called_once_with(output_dir="./.chroma_db")
        mock_service.query_stream.assert_called_once_with("テストの質問")

        # ストリーミング出力（flush=True）と最後の改行の検証
        assert mock_print.call_count == 4
        mock_print.assert_any_call("Hello", end="", flush=True)
        mock_print.assert_any_call(", ", end="", flush=True)
        mock_print.assert_any_call("world!", end="", flush=True)
        mock_print.assert_called_with()  # 引数なしの print() （改行）
