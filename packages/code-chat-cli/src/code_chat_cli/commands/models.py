"""モデル関連のコマンドハンドラを提供するモジュール."""

from typing import Any

from code_chat_cli.logger import get_logger, log_exception

# logger を定義
logger = get_logger(__name__)


def handle_list_models(client: Any) -> None:
    """利用可能な Gemini モデル一覧を取得して標準出力に表示します.

    Args:
        client (Any): Gemini API クライアントインスタンス.

    Raises:
        Exception: モデル一覧の取得時にエラーが発生した場合.

    """
    try:
        print("利用可能なモデル一覧:")
        for model in client.models.list():
            if "generateContent" in model.supported_actions:
                model_id = model.name.replace("models/", "")
                print(f"- {model_id} ({model.display_name})")
    # 例外の種類を問わず, ログに記録してから再送出する (握りつぶさない).
    except Exception:
        log_exception(logger, "モデル一覧の取得に失敗しました")
        raise
