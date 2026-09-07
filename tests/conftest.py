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


# @pytest.fixture
# def mock_args():
#    args = MagicMock()
#    args.command = None
#    args.list_models = False
#    return args
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
