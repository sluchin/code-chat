# pylint: disable=redefined-outer-name
"""`code_chat_cli.commands.models` モジュールのテスト."""

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from code_chat_cli.commands.models import handle_list_models
from code_chat_cli.logger import set_trace
from google.genai.errors import APIError


class TestHandleListModels:
    """`handle_list_models` のテスト."""

    def test_handle_list_models_failure(self, mock_client: MagicMock) -> None:
        """model.list() で例外が発生した場合, 例外がログ出力されて再送出されることを検証する."""
        # client.models.list() が例外を発生させるようにモックを設定
        mock_client.models.list.side_effect = Exception("API Error")

        with pytest.raises(Exception, match="API Error"):
            handle_list_models(mock_client)

        # 18-20行目の try-except ブロックが確実に通過されたことを検証
        mock_client.models.list.assert_called_once()

    @pytest.mark.parametrize("trace", [False, True])
    def test_handle_list_models_api_error_failure(
        self, mock_client: MagicMock, caplog, trace
    ) -> None:
        """Gemini API のエラーは再送出され, トレースバックは --trace 指定時だけ出力されるか検証する."""
        mock_client.models.list.side_effect = APIError(
            403, {"error": {"message": "PERMISSION_DENIED"}}
        )
        set_trace(trace)

        try:
            with (
                caplog.at_level(logging.ERROR),
                pytest.raises(APIError, match="PERMISSION_DENIED"),
            ):
                handle_list_models(mock_client)
        finally:
            set_trace(False)

        record = next(
            r
            for r in caplog.records
            if "モデル一覧の取得に失敗しました" in r.getMessage()
        )
        assert "PERMISSION_DENIED" in record.getMessage() or trace
        assert (record.exc_info is not None) is trace

    def test_handle_list_models_retry_exception(
        self, mock_client: MagicMock, capsys, no_retry_sleep
    ) -> None:
        """一時的なエラー (503) は, リトライされ, 成功すればモデル一覧が表示されるか検証する."""
        model = SimpleNamespace(
            name="models/gemini-flash",
            display_name="Gemini Flash",
            supported_actions=["generateContent"],
        )
        mock_client.models.list.side_effect = [
            APIError(
                503, {"error": {"message": "high demand", "status": "UNAVAILABLE"}}
            ),
            [model],
        ]

        handle_list_models(mock_client)

        assert "- gemini-flash (Gemini Flash)" in capsys.readouterr().out
        no_retry_sleep.assert_called_once()
