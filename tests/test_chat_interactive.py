"""インタラクティブモードの終了例外ハンドリングテスト."""

from unittest.mock import MagicMock, patch

import pytest
from code_chat_cli.chat import main


@pytest.mark.parametrize("exception_type", [KeyboardInterrupt, EOFError])
def test_main_interactive_mode_exit_exceptions(
    exception_type: type[BaseException],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """input() 実行時に KeyboardInterrupt や EOFError が発生した場合、正常終了 (SystemExit: 0) することを検証する.

    Args:
        exception_type (type[BaseException]): 発生させる例外クラス (KeyboardInterrupt または EOFError).
        monkeypatch (pytest.MonkeyPatch): 環境変数やモジュール属性を事前設定するフィクスチャ.
    """
    # 最小限の引数セットを擬似設定
    test_args = ["chat.py"]
    monkeypatch.setattr("sys.argv", test_args)

    # クライアントおよび引数のモック設定 (文字列属性を明示)
    mock_client = MagicMock()
    mock_args = MagicMock()
    mock_args.debug = False
    mock_args.log_level = "INFO"
    mock_args.list_models = False
    mock_args.generate_commit_msg = False
    mock_args.review = False
    mock_args.model = "gemini-flash-latest"  # ★ 文字列を指定
    mock_args.prompt = None  # ★ None または文字列
    mock_args.context = None  # ★ None または文字列
    mock_args.output_path = None
    mock_args.auto_save = False

    # 事前処理をパスさせて確実に input() の例外に到達させる
    with (
        patch("code_chat_cli.chat.parse_args", return_value=mock_args),
        patch("code_chat_cli.chat._setup_cli_logging"),
        patch("code_chat_cli.chat.get_gemini_client", return_value=mock_client),
        patch("code_chat_cli.chat._handle_subcommands"),
        patch("builtins.input", side_effect=exception_type),
        pytest.raises(SystemExit) as exc_info,
    ):
        main()

    # sys.exit(0) で正常終了したことを検証
    assert exc_info.value.code == 0
