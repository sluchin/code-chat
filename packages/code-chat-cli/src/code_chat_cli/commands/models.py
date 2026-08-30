from typing import Any

from code_chat_cli.logger import get_logger

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
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("モデル一覧の取得に失敗しました")
        raise
