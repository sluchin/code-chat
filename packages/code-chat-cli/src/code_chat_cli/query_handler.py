"""Gemini API と MCP サーバー間の Tool Calling 対話ループ実装モジュール."""

import json
import logging
from typing import Any

from code_chat_mcp.mcp_service import McpService
from code_chat_mcp.mcp_tool_info import McpToolInfo
from google import genai
from google.genai import types
from google.genai.errors import APIError
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class QueryHandler:
    """Gemini API と MCP サーバー間の Tool Calling 対話ループを管理するクラス."""

    def __init__(
        self,
        gemini_client: genai.Client,
        mcp_service: McpService,
        model_name: str = "gemini-3.5-flash",
    ) -> None:
        """QueryHandler インスタンスを初期化します.

        Args:
            gemini_client (genai.Client): google-genai の Client インスタンス.
            mcp_service (McpService): 複数の MCP サーバーを管理する McpService インスタンス.
            model_name (str): 使用する Gemini モデル名.

        """
        self.client = gemini_client
        self.mcp_service = mcp_service
        self.model_name = model_name

    @staticmethod
    def _is_rate_limit_error(exception: BaseException) -> bool:
        """429 RESOURCE_EXHAUSTED エラーかどうかを判定します.

        Args:
            exception (BaseException): 判定対象の例外オブジェクト.

        Returns:
            bool: 429 エラーである場合は True, それ以外は False.

        """
        if isinstance(exception, APIError):
            if exception.code == 429:
                return True
            if "429" in str(exception):
                return True
        return False

    @retry(
        retry=retry_if_exception(_is_rate_limit_error),
        wait=wait_exponential(multiplier=2, min=5, max=60),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _generate_content_with_retry(
        self, contents: list[Any], config: types.GenerateContentConfig
    ) -> types.GenerateContentResponse:
        """429 レート制限エラー発生時に自動リトライを行う GenerateContent 呼び出しラッパー.

        Args:
            contents (list[Any]): 送信するコンテンツのリスト.
            config (types.GenerateContentConfig): 生成設定オブジェクト.

        Returns:
            types.GenerateContentResponse: Gemini からのレスポンスオブジェクト.

        """
        return self.client.models.generate_content(
            model=self.model_name,
            contents=contents,
            config=config,
        )

    async def run(self, user_prompt: str) -> str:
        """ユーザープロンプトを受け取り, MCP ツールの実行を経由して最終回答を取得します.

        Args:
            user_prompt (str): ユーザーから入力されたプロンプト文字列.

        Returns:
            str: Gemini からの最終回答テキスト.

        """
        # 各 MCP サーバーからツール一覧を取得し,
        # "server_name__tool_name" 形式で Gemini 用へ変換
        declarations = self._format_tools_for_gemini(
            await self.mcp_service.get_all_tools()
        )

        # Gemini に渡す Tool 設定オブジェクト
        config = types.GenerateContentConfig(
            tools=[{"function_declarations": declarations}] if declarations else None,
            temperature=0.2,
        )

        # 会話履歴メッセージの初期化
        contents: list[Any] = [user_prompt]

        # Tool Calling ループ (ツールの呼び出し要求がなくなるまで反復)
        while True:
            logger.info("Gemini API にリクエストを送信中...")
            response = self._generate_content_with_retry(
                contents=contents,
                config=config,
            )

            # 会話履歴にアシスタントのレスポンスを追加
            if response.candidates and response.candidates[0].content:
                contents.append(response.candidates[0].content)

            # Gemini から Tool Call (function_call) 要求があるか検証
            if not response.function_calls:
                # ツール呼び出しが必要ない場合, テキスト回答を抽出して終了
                return response.text or ""

            # 要求されたツールを実行
            for call in response.function_calls:
                tool_args = dict(call.args) if call.args else {}

                # "server_name__tool_name" から server_name と tool_name を分離
                if "__" in call.name:
                    server_name, tool_name = call.name.split("__", 1)
                else:
                    server_name, tool_name = "default", call.name

                print(f"[MCP Tool Executing] {call.name}({json.dumps(tool_args)})")
                logger.info(
                    "MCP ツール (Server: %s, Tool: %s) を引数 %s で実行します",
                    server_name,
                    tool_name,
                    tool_args,
                )

                # McpService 経由で対象の MCP サーバープロセスを特定してツールを実行
                tool_result = await self.mcp_service.call_tool(
                    server_name=server_name,
                    tool_name=tool_name,
                    arguments=tool_args,
                )

                # MCP の実行結果テキストを結合
                result_text = "\n".join(
                    [
                        content.text
                        for content in tool_result.content
                        if content.type == "text"
                    ]
                )

                print(
                    f"[MCP Tool Result] {result_text[:100]}..."
                    if len(result_text) > 100
                    else f"[MCP Tool Result] {result_text}"
                )

                # Gemini に返答する際は, Gemini が認識している
                # call.name (プレフィックス付き) を設定
                function_response_part = types.Part.from_function_response(
                    name=call.name,
                    response={"result": result_text},
                )
                contents.append(
                    types.Content(role="user", parts=[function_response_part])
                )

    def _format_tools_for_gemini(
        self, mcp_tools: list[McpToolInfo]
    ) -> list[dict[str, Any]]:
        """MCP ツール一覧を Gemini API 用の function_declarations 形式に変換します.

        Args:
            mcp_tools (list[McpToolInfo]): MCP サーバーから取得したツール情報のリスト.

        Returns:
            list[dict[str, Any]]: Gemini API の GenerateContentConfig に渡すための関数宣言リスト.

        """
        declarations: list[dict[str, Any]] = []

        # mcp_tools はリストなので直接ループ（.items() は不要）
        for tool in mcp_tools:
            # tool.inputSchema (または dict 化したパラメータ) をサニタイズ
            raw_parameters = (
                tool.input_schema.model_dump()
                if hasattr(tool.input_schema, "model_dump")
                else tool.input_schema
            )
            formatted_name = f"{tool.server_name}__{tool.name}"
            declaration = {
                "name": formatted_name,
                "description": tool.description or "",
                # "parameters": tool.input_schema,
                "parameters": self._sanitize_schema(raw_parameters),
            }
            declarations.append(declaration)

        return declarations

    def _sanitize_schema(self, schema: dict[str, Any] | None) -> dict[str, Any] | None:
        """Gemini API に適合しない非標準の JSON Schema フィールドを再帰的に削除します.

        Args:
            schema (dict[str, Any] | None): サニタイズ対象の JSON Schema 辞書.

        Returns:
            dict[str, Any] | None: サニタイズされた JSON Schema 辞書.

        """
        if schema is None:
            return None

        # Gemini の FunctionDeclaration パラメータで許可されていない非標準/メタ属性
        disallowed_keys = {
            "$schema",
            "exclusiveMaximum",
            "exclusiveMinimum",
            "$id",
            "$comment",
            "additionalProperties",
            "additional_properties",
        }

        sanitized: dict[str, Any] = {}
        for key, value in schema.items():
            if key in disallowed_keys:
                continue

            if isinstance(value, dict):
                sanitized[key] = self._sanitize_schema(value)
            elif isinstance(value, list):
                sanitized[key] = [
                    self._sanitize_schema(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                sanitized[key] = value

        return sanitized
