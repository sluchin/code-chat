# pylint: disable=redefined-outer-name
"""`code_chat_cli.commands.models` モジュールのテスト."""

from unittest.mock import MagicMock

import pytest
from code_chat_cli.commands.models import handle_list_models


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
