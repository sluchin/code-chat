"""Gemini CLI Tool - API Client Configuration."""

import os
import sys

from google import genai

from code_chat_cli.logger import get_logger

logger = get_logger(__name__)


class ClientConfigError(Exception):
    """クライアント設定や環境変数に関する例外."""


def get_gemini_client() -> genai.Client:
    """環境変数 GEMINI_API_KEY から API キーを取得して Gemini クライアントを作成する.

    環境変数が未設定の場合は、標準エラー出力にエラーメッセージを出力して処理を終了します.

    Returns:
        genai.Client: 初期化された Gemini API クライアントインスタンス.

    Raises:
        SystemExit: 環境変数 `GEMINI_API_KEY` が設定されていない場合にステータスコード 1 で終了します.
    """
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        logger.error("環境変数 GEMINI_API_KEY が設定されていません。")
        print(
            "実行前に export GEMINI_API_KEY='your-api-key' を設定してください。",
            file=sys.stderr,
        )
        raise ClientConfigError("GEMINI_API_KEY is missing")

    return genai.Client(api_key=api_key)
