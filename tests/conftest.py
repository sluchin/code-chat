"""pytest の共通フィクスチャ定義モジュール."""

from unittest.mock import MagicMock
import pytest


@pytest.fixture
def mock_client() -> MagicMock:
    """Gemini API クライアントのモックフィクスチャ."""
    client = MagicMock()
    # 必要に応じてデフォルトの振る舞いを記述
    return client
