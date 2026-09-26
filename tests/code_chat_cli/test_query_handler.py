# pylint: disable=redefined-outer-name,protected-access
"""`code_chat_cli.query_handler` モジュールのテスト."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from code_chat_cli.query_handler import QueryHandler
from code_chat_mcp.mcp_tool_info import McpToolInfo
from google.genai.errors import APIError


def _response(text="", function_calls=None, content="CONTENT", candidates=True):
    """generate_content のレスポンスのモックを作成する."""
    response = MagicMock()
    response.candidates = [SimpleNamespace(content=content)] if candidates else []
    response.function_calls = function_calls
    response.text = text
    return response


def _call(name, args=None):
    return SimpleNamespace(name=name, args=args)


def _tool_result(*parts):
    return SimpleNamespace(
        content=[SimpleNamespace(type=t, text=text) for t, text in parts]
    )


@pytest.fixture
def mcp_service():
    """McpService のモック."""
    service = MagicMock()
    service.get_all_tools = AsyncMock(return_value=[])
    service.call_tool = AsyncMock(return_value=_tool_result(("text", "tool output")))
    return service


@pytest.fixture
def client():
    """Gemini クライアントのモック."""
    return MagicMock()


@pytest.fixture
def handler(client, mcp_service):
    """QueryHandler インスタンス."""
    return QueryHandler(gemini_client=client, mcp_service=mcp_service)


@pytest.fixture(autouse=True)
def no_sleep():
    """tenacity のリトライ待機をスキップする."""
    with patch("tenacity.nap.time.sleep"):
        yield


class TestIsRateLimitError:
    """`QueryHandler._is_rate_limit_error` のテスト."""

    def test_is_rate_limit_error_success(self):
        """429 エラーの判定を検証."""
        assert QueryHandler._is_rate_limit_error(APIError(429, {})) is True
        assert (
            QueryHandler._is_rate_limit_error(APIError("429 RESOURCE_EXHAUSTED", {}))
            is True
        )
        assert QueryHandler._is_rate_limit_error(APIError(500, {})) is False
        assert QueryHandler._is_rate_limit_error(ValueError("429")) is False

    def test_is_rate_limit_error_daily_quota(self):
        """1 日あたりの上限 (RPD) の 429 は, 待っても回復しないためリトライ対象にならないか検証."""
        error = APIError(429, {"error": {"message": "GenerateRequestsPerDay exceeded"}})

        assert QueryHandler._is_rate_limit_error(error) is False


class TestInit:
    """`QueryHandler.__init__` のテスト."""

    def test_init_defaults_success(self, client, mcp_service):
        """初期化時の属性と既定モデルを検証."""
        handler = QueryHandler(client, mcp_service)

        assert handler.client is client
        assert handler.mcp_service is mcp_service
        assert handler.model_name == "gemini-3.5-flash"


class TestGenerateContentWithRetry:
    """`QueryHandler._generate_content_with_retry` のテスト."""

    def test_generate_content_with_retry_does_not_retry_other_errors_failure(
        self, handler, client
    ):
        """429 以外のエラーは再試行せずに送出されるか検証."""
        client.models.generate_content.side_effect = APIError(500, {})

        with pytest.raises(APIError):
            handler._generate_content_with_retry(contents=["x"], config=MagicMock())

        assert client.models.generate_content.call_count == 1

    def test_generate_content_with_retry_daily_quota_failure(self, handler, client):
        """1 日あたりの上限は, リトライせずに送出されるか検証."""
        client.models.generate_content.side_effect = APIError(
            429, {"error": {"message": "GenerateRequestsPerDay exceeded"}}
        )

        with pytest.raises(APIError):
            handler._generate_content_with_retry(contents=["x"], config=MagicMock())

        assert client.models.generate_content.call_count == 1

    def test_generate_content_with_retry_retries_on_rate_limit_exception(
        self, handler, client
    ):
        """429 の場合は再試行し, 成功すればその結果を返すか検証."""
        client.models.generate_content.side_effect = [APIError(429, {}), "ok"]

        result = handler._generate_content_with_retry(
            contents=["x"], config=MagicMock()
        )

        assert result == "ok"
        assert client.models.generate_content.call_count == 2

    def test_generate_content_with_retry_logs_retry_exception(
        self, handler, client, caplog
    ):
        """リトライの待機に入る前に, 原因と再試行の回数が警告として出力されるか検証 (無言で待たない)."""
        minute_limit = APIError(
            429,
            {
                "error": {
                    "message": "quota exceeded, limit: 5",
                    "status": "RESOURCE_EXHAUSTED",
                    "details": [
                        {
                            "violations": [
                                {
                                    "quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"
                                }
                            ]
                        }
                    ],
                }
            },
        )
        client.models.generate_content.side_effect = [minute_limit, "ok"]

        handler._generate_content_with_retry(contents=["x"], config=MagicMock())

        assert "レート制限のため" in caplog.text
        assert "(1/5)" in caplog.text
        assert "1 分あたりのリクエスト上限" in caplog.text


class TestRun:
    """`QueryHandler.run` のテスト."""

    def test_run_returns_text_without_tool_calls_success(
        self, handler, client, mcp_service
    ):
        """ツール呼び出しが無い場合はテキストを返し, ツール未定義なら tools が None か検証."""
        client.models.generate_content.return_value = _response(text="answer")

        result = asyncio.run(handler.run("question"))

        assert result == "answer"
        config = client.models.generate_content.call_args.kwargs["config"]
        assert config.tools is None
        mcp_service.call_tool.assert_not_awaited()

    def test_run_executes_tool_calls_and_loops_success(
        self, handler, client, mcp_service, capsys
    ):
        """ツール呼び出しを実行して結果を返送し, 最終回答を返すか検証."""
        mcp_service.get_all_tools.return_value = [
            McpToolInfo("git", "status", "show", {"type": "object"}),
        ]
        mcp_service.call_tool.return_value = _tool_result(
            ("text", "line1"), ("image", "ignored"), ("text", "line2")
        )
        client.models.generate_content.side_effect = [
            _response(function_calls=[_call("git__status", {"path": "."})]),
            _response(text="done"),
        ]

        result = asyncio.run(handler.run("what changed?"))

        assert result == "done"
        mcp_service.call_tool.assert_awaited_once_with(
            server_name="git", tool_name="status", arguments={"path": "."}
        )
        first_config = client.models.generate_content.call_args_list[0].kwargs["config"]
        assert first_config.tools is not None
        # 2 回目のリクエストにはモデルの応答とツール結果が含まれる
        second_contents = client.models.generate_content.call_args_list[1].kwargs[
            "contents"
        ]
        assert second_contents[0] == "what changed?"
        assert second_contents[1] == "CONTENT"
        function_response = second_contents[2].parts[0].function_response
        assert function_response.name == "git__status"
        assert function_response.response == {"result": "line1\nline2"}
        out = capsys.readouterr().out
        assert '[MCP Tool Executing] git__status({"path": "."})' in out
        assert "[MCP Tool Result] line1\nline2" in out

    def test_run_handles_empty_response(self, handler, client):
        """テキストもコンテンツも無いレスポンスでも空文字を返すか検証."""
        client.models.generate_content.return_value = _response(
            text=None, candidates=False
        )

        assert asyncio.run(handler.run("question")) == ""

    def test_run_tool_name_without_server_prefix(self, handler, client, mcp_service):
        """サーバー名の接頭辞が無いツール名は default サーバーとして扱われるか検証."""
        client.models.generate_content.side_effect = [
            _response(function_calls=[_call("plain_tool")], content=None),
            _response(text="done"),
        ]

        asyncio.run(handler.run("q"))

        mcp_service.call_tool.assert_awaited_once_with(
            server_name="default", tool_name="plain_tool", arguments={}
        )

    def test_run_truncates_long_tool_result(self, handler, client, mcp_service, capsys):
        """長いツール結果は表示時に 100 文字で省略されるか検証."""
        mcp_service.call_tool.return_value = _tool_result(("text", "x" * 150))
        client.models.generate_content.side_effect = [
            _response(function_calls=[_call("a__b")]),
            _response(text="done"),
        ]

        asyncio.run(handler.run("q"))

        assert f"[MCP Tool Result] {'x' * 100}..." in capsys.readouterr().out


class TestFormatToolsForGemini:
    """`QueryHandler._format_tools_for_gemini` のテスト."""

    def test_format_tools_for_gemini_success(self, handler):
        """model_dump を持つスキーマと辞書スキーマが共に関数宣言へ変換されるか検証."""
        model_like = SimpleNamespace(
            model_dump=lambda: {"type": "object", "additionalProperties": False}
        )
        tools = [
            McpToolInfo("git", "status", "show", model_like),  # type: ignore[arg-type]
            McpToolInfo("fs", "read", None, {"type": "object", "$schema": "x"}),
        ]

        declarations = handler._format_tools_for_gemini(tools)

        assert declarations == [
            {
                "name": "git__status",
                "description": "show",
                "parameters": {"type": "object"},
            },
            {"name": "fs__read", "description": "", "parameters": {"type": "object"}},
        ]


class TestSanitizeSchema:
    """`QueryHandler._sanitize_schema` のテスト."""

    def test_sanitize_schema_success(self, handler):
        """非標準フィールドが再帰的に削除されるか検証."""
        schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "additionalProperties": False,
            "additional_properties": False,
            "properties": {
                "n": {"type": "integer", "exclusiveMinimum": 0, "$comment": "c"},
                "choice": {"anyOf": [{"type": "string", "$id": "x"}, "raw"]},
            },
            "required": ["n"],
        }

        assert handler._sanitize_schema(schema) == {
            "type": "object",
            "properties": {
                "n": {"type": "integer"},
                "choice": {"anyOf": [{"type": "string"}, "raw"]},
            },
            "required": ["n"],
        }
        assert handler._sanitize_schema(None) is None
