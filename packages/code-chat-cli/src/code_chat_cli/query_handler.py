"""Gemini API と MCP サーバー間の Tool Calling 対話ループ実装モジュール."""

import json
import logging
from typing import Any

from google import genai
from google.genai import types

from code_chat_cli.api import call_with_retry
from code_chat_mcp.mcp_service import McpService
from code_chat_mcp.mcp_tool_info import McpToolInfo

logger = logging.getLogger(__name__)


class QueryHandler:
    """Gemini API と MCP サーバー間の Tool Calling 対話ループを管理するクラス."""

    def __init__(
        self,
        gemini_client: genai.Client,
        mcp_service: McpService,
        model_name: str | None = None,
        cached_content: str | None = None,
    ) -> None:
        """QueryHandler インスタンスを初期化します.

        Args:
            gemini_client (genai.Client): google-genai の Client インスタンス.
            mcp_service (McpService): 複数の MCP サーバーを管理する McpService インスタンス.
            model_name (str | None): 使用する Gemini モデル名. 省略時は `gemini-3.5-flash`.
            キャッシュを使う場合は, キャッシュのモデルを指定する.
            cached_content (str | None): 使用するキャッシュ名 (`cachedContents/<ID>`). 省略時はキャッシュを使わない.
                ツール定義はキャッシュに含まれないため, Gemini API がエラーを返す場合がある.

        """
        self.client = gemini_client
        self.mcp_service = mcp_service
        self.model_name = model_name or "gemini-3.5-flash"
        self.cached_content = cached_content

    def _generate_content_with_retry(
        self, contents: list[Any], config: types.GenerateContentConfig
    ) -> types.GenerateContentResponse:
        """一時的なエラー (503 / 429 など) の場合にリトライを行う GenerateContent 呼び出しラッパー.

        Args:
            contents (list[Any]): 送信するコンテンツのリスト.
            config (types.GenerateContentConfig): 生成設定オブジェクト.

        Returns:
            types.GenerateContentResponse: Gemini からのレスポンスオブジェクト.

        """
        response: types.GenerateContentResponse = call_with_retry(
            self.client.models.generate_content,
            model=self.model_name,
            contents=contents,
            config=config,
        )
        return response

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
            cached_content=self.cached_content,
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

            # 要求されたツールを実行し, 結果は, 呼び出しの数と同じ数の Part にまとめて 1 回で返す
            # (並列の呼び出しの結果を別々に返すと, Gemini API が 400 を返す)
            response_parts: list[types.Part] = []
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

                # 長い結果は, 表示だけ先頭の 100 文字に省略する (Gemini には全文を渡す)
                print(
                    f"[MCP Tool Result] {result_text[:100]}..."
                    if len(result_text) > 100
                    else f"[MCP Tool Result] {result_text}"
                )

                # Gemini に返答する際は, Gemini が認識している
                # call.name (プレフィックス付き) を設定
                response_parts.append(
                    types.Part.from_function_response(
                        name=call.name,
                        response={"result": result_text},
                    )
                )

            contents.append(types.Content(role="user", parts=response_parts))

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

            # ネストした辞書や, リスト内の辞書も, 再帰的に処理する
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
