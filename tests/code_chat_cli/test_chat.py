# pylint: disable=redefined-outer-name,protected-access,too-many-public-methods
"""`code_chat_cli.chat` モジュールのテスト."""

import io
import logging
import subprocess
import sys
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.genai.errors import APIError

from code_chat_cli.cache_error import CacheError
from code_chat_cli.chat import (
    _append_rag_context,
    _build_chat_config,
    _build_context_prompt,
    _build_send_text,
    _cached_content_name,
    _handle_cache_subcommand,
    _handle_dryrun,
    _handle_login,
    _handle_mcp_interactive,
    _handle_mcp_single_turn,
    _handle_mcp_subcommand,
    _handle_prompt_mode,
    _handle_rag_subcommand,
    _handle_subcommands,
    _load_files_context,
    _log_cache_usage,
    _require_rag_api_key,
    _resolve_cache_settings,
    _retrieve_rag_context,
    _run_interactive_loop,
    _run_single_turn_mode,
    _setup_cli_logging,
    main,
)
from code_chat_cli.cli_args import CliArgs
from code_chat_cli.oauth_error import OAuthError


def _cli_args(**overrides) -> SimpleNamespace:
    """CliArgs の既定値に overrides を適用した parse_args 戻り値のモックを作成する."""
    values = {"model": "gemini-flash-latest", **overrides}
    return SimpleNamespace(**asdict(CliArgs(**values)))


def _chunk(text):
    return SimpleNamespace(text=text)


class TestRunSingleTurnMode:
    """`_run_single_turn_mode` のテスト."""

    def test_run_single_turn_mode_mcp_success(self):
        """--mcp 指定時は MCP のワンショット処理に振り分けられるか検証."""
        # --mcp 指定のワンショット実行を想定した引数と履歴を用意
        args = _cli_args(mcp=True, prompt="git status")
        history: list[str] = []

        # MCP の実行はモック化し, 実際の MCP サーバーへは接続しない
        with patch(
            "code_chat_cli.chat.handle_mcp_run", new=AsyncMock(return_value="clean")
        ) as run:
            _run_single_turn_mode(MagicMock(), args, history)

        # プロンプトが MCP に渡され, 履歴に User → Gemini の順で記録されること
        run.assert_awaited_once_with(
            user_prompt="git status",
            config_path=None,
            use_oauth=False,
            model_name="gemini-flash-latest",
            cached_content=None,
        )
        assert history == ["### User (MCP)\n\ngit status", "### Gemini (MCP)\n\nclean"]

    def test_run_single_turn_mode_context_history_success(self):
        """chat_history にコード本文ではなくメタデータ（ファイル名・サイズ）が記録されるか検証."""
        # Gemini の Chat をモック化 (応答テキストのみ設定)
        mock_chat = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Hello response"
        mock_chat.send_message.return_value = mock_response

        # ファイル指定 + プロンプト + Write モードのコンテキスト実行
        cli_args = _cli_args(
            files=["src/main.py"],
            context="print('hello world')\n",  # 20 bytes
            prompt="コードをレビューしてください",
            write_mode=True,
        )

        chat_history = []

        # 実行 (書き込みの確認プロンプトは表示させない)
        with patch("code_chat_cli.chat.handle_write_mode_confirmation"):
            _run_single_turn_mode(mock_chat, cli_args, chat_history)

        # chat_history[0] にファイル名とバイトサイズが含まれているか検証
        assert len(chat_history) > 0
        history_entry = chat_history[0]

        # バイト計算に合わせて 20 bytes に変更, または動的に判定
        context_bytes = len(cli_args.context.encode("utf-8"))
        expected_metadata = f"[ファイル読み込み: src/main.py ({context_bytes} bytes)]"

        assert expected_metadata in history_entry
        assert "[指示]: コードをレビューしてください" in history_entry
        # ソースコード本文自体は履歴に含まれていないことを確認
        assert "print('hello world')" not in history_entry


class TestRunInteractiveLoop:
    """`_run_interactive_loop` のテスト."""

    def test_run_interactive_loop_exit_command_success(
        self, monkeypatch, mock_gemini_client, capsys
    ):
        """対話モードで 'exit' を入力した際にメッセージ送信と正常終了が行われるか検証."""
        # 標準入力に「こんにちは」→ exit を流し込み, 対話モードで起動する
        user_input = "こんにちは\nexit\n"
        monkeypatch.setattr("sys.stdin", io.StringIO(user_input))
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("sys.argv", ["chat.py"])

        # 実行
        main()

        # chat.send_message_stream が「こんにちは」で呼び出されたか検証
        mock_gemini_client["chat"].send_message_stream.assert_called_once_with(
            "こんにちは"
        )
        assert "会話を終了します." in capsys.readouterr().out

    def test_run_interactive_loop_write_mode_success(
        self, monkeypatch, mock_gemini_client, mock_args
    ):
        """対話ループ内で write_mode=True の時, 送信メッセージ末尾に指示テキストが追加されるか検証."""
        # write_mode を True に設定
        mock_args.return_value.context = None
        mock_args.return_value.prompt = None
        mock_args.return_value.write_mode = True
        mock_args.return_value.target_path = "sample.py"

        # ストリーミングレスポンスのモック化
        mock_chunk = SimpleNamespace(text="```python\nprint('hello')\n```")
        mock_gemini_client["chat"].send_message_stream.return_value = [mock_chunk]

        # 1回目にプロンプト入力, 2回目に "exit" を入力
        inputs = iter(["関数を追加してください", "exit"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))

        # handle_write_mode_confirmation の呼び出しを抑制
        with patch("code_chat_cli.chat.handle_write_mode_confirmation"):
            main()

        # chat.send_message_stream に渡された第1引数（index 0）を検証
        assert mock_gemini_client["chat"].send_message_stream.call_count == 1
        sent_prompt = mock_gemini_client["chat"].send_message_stream.call_args[0][0]

        # 送信テキスト末尾に (※指示に従って修正した... が付加されていること
        assert sent_prompt.startswith("関数を追加してください")
        assert (
            "(※指示に従って修正した「完全なコード全体」を省略せずに1つのコードブロックで出力してください)"
            in sent_prompt
        )

    def test_run_interactive_loop_mcp_command_success(self, monkeypatch):
        """対話ループで /mcp が MCP 処理に振り分けられ, 通常送信されないか検証."""
        # 1 回目に /mcp コマンド, 2 回目に exit を入力
        inputs = iter(["/mcp status", "exit"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))
        chat = MagicMock()

        # readline 履歴の読み込みと MCP 処理をモック化し, 対話ループを直接実行する
        with (
            patch("code_chat_cli.chat.setup_readline_history"),
            patch("code_chat_cli.chat._handle_mcp_interactive") as handler,
        ):
            _run_interactive_loop(chat, _cli_args(), [])

        # /mcp は MCP 処理に振り分けられ, 通常の Gemini 送信は行われないこと
        handler.assert_called_once()
        chat.send_message_stream.assert_not_called()

    @pytest.mark.parametrize("exception_type", [KeyboardInterrupt, EOFError])
    def test_run_interactive_loop_interrupt_exception(
        self,
        exception_type: type[BaseException],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """input() 実行時に KeyboardInterrupt や EOFError が発生した場合, 正常終了 (SystemExit: 0) することを検証する."""
        # 最小限の引数セットを擬似設定
        test_args = ["chat.py"]
        monkeypatch.setattr("sys.argv", test_args)

        # クライアントおよび引数のモック設定 (文字列属性を明示)
        mock_client = MagicMock()
        mock_args = _cli_args()

        # 事前処理をパスさせて確実に input() の例外に到達させる
        with (
            patch("code_chat_cli.chat.parse_args", return_value=mock_args),
            patch("code_chat_cli.chat._setup_cli_logging"),
            patch(
                "code_chat_cli.chat.get_gemini_client",
                return_value=mock_client,
            ),
            patch("code_chat_cli.chat._handle_subcommands"),
            patch("builtins.input", side_effect=exception_type),
            pytest.raises(SystemExit) as exc_info,
        ):
            main()

        # sys.exit(0) で正常終了したことを検証
        assert exc_info.value.code == 0
        assert "会話を終了します." in capsys.readouterr().out

    def test_run_interactive_loop_empty_input(
        self, monkeypatch, mock_gemini_client, mock_args
    ):
        """対話ループで空文字（Enterのみ）を入力した場合, continue でループが継続されるか検証."""
        # 初期プロンプトやコンテキストがないインタラクティブモードを設定
        mock_args.return_value.context = None
        mock_args.return_value.prompt = None

        # 1回目に空文字 "", 2回目に "exit" を返すイテレータを作成
        inputs = iter(["", "exit"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))

        main()

        # 空文字の時は API 送信が行われないため, send_message_stream の呼び出し回数は 0 回であることを確認
        assert mock_gemini_client["chat"].send_message_stream.call_count == 0


class TestHandleSlashCommand:
    """`_handle_slash_command` のテスト."""

    def test_handle_slash_command_save_success(self, monkeypatch, mock_args):
        """対話ループ内で /save <filepath> を入力した場合, 指定パスへ履歴が保存されるか検証."""
        mock_args.return_value.context = None
        mock_args.return_value.prompt = None

        # 1回目に "/save custom_log.md", 2回目に "exit" を入力
        inputs = iter(["/save custom_log.md", "exit"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))

        with patch("code_chat_cli.chat.save_chat_history") as mock_save:
            main()

            # save_chat_history が "custom_log.md" 引数で呼び出されたことを検証
            mock_save.assert_called_once()
            assert mock_save.call_args[0][0] == "custom_log.md"

    def test_handle_slash_command_save_no_path_failure(self, monkeypatch, mock_args):
        """対話ループ内で引数なしの /save を入力した場合, エラーログが出力され保存されないか検証."""
        mock_args.return_value.context = None
        mock_args.return_value.prompt = None

        # 1回目に "/save"（引数なし）, 2回目に "exit" を入力
        inputs = iter(["/save", "exit"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))

        with patch("code_chat_cli.chat.save_chat_history") as mock_save:
            main()

            # 保存先が無いため save_chat_history は呼ばれないことを検証
            mock_save.assert_not_called()


class TestBuildSendText:
    """`_build_send_text` のテスト."""

    def test_build_send_text_files_success(self, tmp_path):
        """files 指定時はファイル内容が付加されるか検証."""
        # 読み込ませるファイルを用意
        target = tmp_path / "a.py"
        target.write_text("x = 1", encoding="utf-8")

        # 実行: files 指定で送信テキストを構築
        text = _build_send_text("explain", _cli_args(files=[str(target)]), None)

        # 入力の後ろにファイル名の見出し付きで内容が付加されること
        assert text.startswith("explain\n\n--- File:")
        assert "x = 1" in text

    def test_build_send_text_rag_write_mode_success(self):
        """RAG コンテキストと Write モードの指示が付加されるか検証."""
        # RAG サービスが関連コード "ctx" を返すようにモック化
        rag = MagicMock()
        rag.get_context.return_value = "ctx"

        # 実行: RAG 有効 + Write モード
        text = _build_send_text("q", _cli_args(write_mode=True), rag)

        # RAG のコンテキストと Write モードの指示が, 両方付加されること
        assert "--- [関連する参照コード (RAG)] ---\nctx" in text
        assert "完全なコード全体" in text

    def test_build_send_text_unreadable_files(self, tmp_path):
        """読み込めるファイルが無い場合は入力がそのまま返るか検証."""
        # 存在しないファイルだけを指定して実行
        text = _build_send_text("q", _cli_args(files=[str(tmp_path / "none")]), None)

        # 読み込めなかった場合は, 入力がそのまま返ること
        assert text == "q"


class TestLoadFilesContext:
    """`_load_files_context` のテスト."""

    def test_load_files_context_success(self, tmp_path, caplog):
        """読み込めたファイルのみがコンテキスト化され, 失敗は警告されるか検証."""
        # 読み込めるファイルと, 存在しないファイルを用意
        good = tmp_path / "a.py"
        good.write_text("print('a')", encoding="utf-8")
        missing = tmp_path / "missing.py"

        # 実行
        result = _load_files_context([str(good), str(missing)])

        # 読み込めたファイルだけが結果に含まれ, 失敗は警告ログに残ること
        assert result == [f"--- File: {good} ---\nprint('a')"]
        assert "の読み込みに失敗しました" in caplog.text


class TestAppendRagContext:
    """`_append_rag_context` のテスト."""

    def test_append_rag_context_empty_result(self, caplog):
        """RAG の検索結果が空の場合は警告し, 元のテキストを返すか検証."""
        # 検索結果が空文字になる RAG サービス
        rag = MagicMock()
        rag.get_context.return_value = ""

        # 実行 (デバッグ出力も確認するため, DEBUG まで記録する)
        with caplog.at_level("DEBUG"):
            result = _append_rag_context("q", "q", rag)

        # 元のテキストは変わらず, 警告ログとデバッグ用の再検索が行われること
        assert result == "q"
        assert "RAG 検索結果が空でした" in caplog.text
        rag.vector_store.search_debug.assert_called_once_with("q")


class TestRetrieveRagContext:
    """`_retrieve_rag_context` のテスト."""

    def test_retrieve_rag_context_exception(self, caplog):
        """RAG 取得時の例外は警告され, 空文字が返るか検証."""
        # 検索時に例外を送出する RAG サービス
        rag = MagicMock()
        rag.get_context.side_effect = RuntimeError("db down")

        # 例外は握りつぶされて空文字が返り, 警告ログが残ること
        assert _retrieve_rag_context(rag, "q") == ""
        assert "RAGコンテキスト取得時にエラーが発生しました" in caplog.text


class TestBuildContextPrompt:
    """`_build_context_prompt` のテスト."""

    def test_build_context_prompt_rag_write_mode_success(self):
        """RAG コンテキストと Write モードの注記がプロンプトに含まれるか検証."""
        # RAG が "rag-ctx" を返す設定
        rag = MagicMock()
        rag.get_context.return_value = "rag-ctx"
        args = _cli_args(context="SRC", prompt="fix it", write_mode=True)

        # 実行
        prompt = _build_context_prompt(args, rag_service=rag)

        # コンテキスト・RAG・指示・Write モードの注記がすべて含まれること
        assert "SRC" in prompt
        assert "rag-ctx" in prompt
        assert "--- [指示] ---\nfix it" in prompt
        assert "完全なコード全体" in prompt

    def test_build_context_prompt_without_prompt(self):
        """プロンプトが無い場合は準備完了の返答を促す文が入るか検証."""
        # プロンプトなしで構築
        prompt = _build_context_prompt(_cli_args(context="SRC", prompt=None))

        # 準備完了の返答を促す文が入ること
        assert "準備ができたら" in prompt


class TestHandleContextMode:
    """`_handle_context_mode` のテスト."""

    def test_handle_context_mode_no_prompt_success(
        self, monkeypatch, mock_gemini_client, mock_args
    ):
        """context あり, prompt なしのルートを通過するか検証."""
        mock_args.return_value.context = "--- [ファイル内容] ---\ndef main(): pass"
        mock_args.return_value.prompt = None
        mock_args.return_value.write_mode = False

        # 初期応答をモック
        mock_response = SimpleNamespace(text="データを読み込みました.")
        mock_gemini_client["chat"].send_message.return_value = mock_response

        # 対話ループを抜けるために input で 'exit' を返す
        monkeypatch.setattr("builtins.input", lambda _: "exit")

        # 実行: context のみ指定されているので, 初期コンテキストが送信される
        main()

        # chat.send_message が適切な初期メッセージで呼び出されたか検証
        mock_gemini_client["chat"].send_message_stream.assert_called_once()
        sent_prompt = mock_gemini_client["chat"].send_message_stream.call_args[0][0]

        assert "以下のソースコード・テキストを読み込んで" in sent_prompt
        assert "データを読み込みました. どのような対応を行いますか？" in sent_prompt

    def test_handle_context_mode_write_mode_success(
        self, monkeypatch, mock_gemini_client, mock_args
    ):
        """context あり, prompt あり, write_mode=True（handle_write_mode_confirmation通過）のルートを検証."""
        mock_args.return_value.context = "--- [ファイル内容] ---\ndef main(): pass"
        mock_args.return_value.prompt = "コードをリファクタリングしてください"
        mock_args.return_value.write_mode = True
        mock_args.return_value.files = ["src/main.py"]

        # ストリーミング初期応答（チャンクのイテレータ）をモック化
        response_text = "```python\ndef main(): print('updated')\n```"
        mock_chunk = SimpleNamespace(text=response_text)
        mock_gemini_client["chat"].send_message_stream.return_value = [mock_chunk]

        # 非ストリーミング（send_message / send_message_with_retry）側の応答も設定
        mock_response = SimpleNamespace(text=response_text)
        mock_gemini_client["chat"].send_message.return_value = mock_response

        # 対話ループを即時終了
        monkeypatch.setattr("builtins.input", lambda _: "exit")

        # handle_write_mode_confirmation の実行を確認するためのモック
        with patch(
            "code_chat_cli.chat.handle_write_mode_confirmation"
        ) as mock_handle_write:
            main()

            # handle_write_mode_confirmation が指定引数で呼び出されたかを検証
            mock_handle_write.assert_called_once_with(["src/main.py"], response_text)

        # 送信されたプロンプト内に注記が含まれているか検証
        # （※ send_message か send_message_stream のどちらで呼ばれたかに応じて検証）
        if mock_gemini_client["chat"].send_message_stream.called:
            sent_prompt = mock_gemini_client["chat"].send_message_stream.call_args[0][0]
        else:
            sent_prompt = mock_gemini_client["chat"].send_message.call_args[0][0]

        assert "※指示に従って修正した「完全なコード全体」を省略せずに" in sent_prompt


class TestHandlePromptMode:
    """`_handle_prompt_mode` のテスト."""

    def test_handle_prompt_mode_success(
        self, monkeypatch, mock_gemini_client, mock_args
    ):
        """プロンプト指定モード時に一括処理して終了するか検証."""
        mock_args.return_value.prompt = "パイプからの入力メッセージ"

        # 対話ループに入った際に即座に EOF（終了）となるよう stdin をモック
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        monkeypatch.setattr("sys.argv", ["chat.py", "-p", "パイプからの入力メッセージ"])

        with patch("code_chat_cli.chat.time.sleep"):
            main()

        # send_message_stream が正しく呼ばれたか検証
        assert mock_gemini_client["chat"].send_message_stream.call_count == 1
        args, _ = mock_gemini_client["chat"].send_message_stream.call_args
        assert "パイプからの入力メッセージ" in args[0]

    def test_handle_prompt_mode_rag_success(self, capsys):
        """RAG 有効時にコンテキストが送信テキストに付加されるか検証."""
        # RAG が "rag-ctx" を返し, Gemini がストリームで "reply" を返す設定
        rag = MagicMock()
        rag.get_context.return_value = "rag-ctx"
        chat = MagicMock()
        chat.send_message_stream.return_value = [_chunk("reply")]
        history: list[str] = []

        # 実行
        _handle_prompt_mode(chat, _cli_args(prompt="q"), history, rag_service=rag)

        # RAG のコンテキストが送信され, 応答が履歴と標準出力に反映されること
        sent = chat.send_message_stream.call_args[0][0]
        assert "rag-ctx" in sent
        assert history[-1] == "### Gemini\n\nreply"
        assert "You > q" in capsys.readouterr().out


class TestSetupCliLogging:
    """`_setup_cli_logging` のテスト."""

    def test_setup_cli_logging_utility_command_success(self):
        """モデル一覧・コミットメッセージ生成時は INFO ログが抑制されるか検証."""
        # ロギングの初期化処理をモック化して, 呼び出しを検証する
        with patch("code_chat_cli.chat.suppress_info_logs") as suppress:
            _setup_cli_logging(_cli_args(list_models=True))

        # INFO ログを抑制する処理が呼ばれること
        suppress.assert_called_once_with()

    def test_setup_cli_logging_utility_command_trace_success(self):
        """モデル一覧などの INFO ログ抑制時でも, --trace の指定が反映されるか検証."""
        with (
            patch("code_chat_cli.chat.suppress_info_logs"),
            patch("code_chat_cli.chat.set_trace") as set_trace,
        ):
            _setup_cli_logging(_cli_args(list_models=True, trace_mode=True))

        set_trace.assert_called_once_with(True)

    def test_setup_cli_logging_debug_mode_success(self):
        """デバッグモードでは DEBUG レベルで初期化されるか検証."""
        # ロギングの初期化処理をモック化して, 呼び出しを検証する
        with patch("code_chat_cli.chat.setup_logging") as setup:
            _setup_cli_logging(_cli_args(debug_mode=True, trace_mode=True))

        # DEBUG レベル・トレース有効で初期化されること
        setup.assert_called_once_with(level_name="DEBUG", trace=True)


class TestLogCacheUsage:
    """`_log_cache_usage` のテスト."""

    def test_log_cache_usage_hit_success(self, caplog):
        """キャッシュが効いた場合は, ヒットしたトークン数と割合が INFO で出力されるか検証."""
        usage = SimpleNamespace(
            prompt_token_count=16718, cached_content_token_count=12264
        )

        with caplog.at_level(logging.INFO):
            _log_cache_usage(usage)

        assert "キャッシュヒット: 12264 / 16718 トークン (73%)" in caplog.text

    def test_log_cache_usage_no_hit(self, caplog):
        """キャッシュが効いていない場合は, INFO には出さず DEBUG にだけ出力されるか検証."""
        usage = SimpleNamespace(prompt_token_count=100, cached_content_token_count=None)

        with caplog.at_level(logging.INFO):
            _log_cache_usage(usage)
        assert "キャッシュヒット" not in caplog.text

        with caplog.at_level(logging.DEBUG, logger="code_chat_cli.chat"):
            _log_cache_usage(usage)
        assert "キャッシュヒットなし (プロンプト: 100 トークン)" in caplog.text

    @pytest.mark.parametrize(
        "usage", [None, MagicMock(), SimpleNamespace(prompt_token_count=0)]
    )
    def test_log_cache_usage_unavailable(self, caplog, usage):
        """使用状況が無い・数値でない・0 の場合は, 何も出力せずに戻るか検証."""
        with caplog.at_level(logging.DEBUG):
            _log_cache_usage(usage)

        assert "キャッシュ" not in caplog.text


class TestResolveCacheSettings:
    """`_resolve_cache_settings` のテスト."""

    def test_resolve_cache_settings_success(self):
        """キャッシュのモデルと, キャッシュ名を指定した生成設定 (システム指示なし) が返るか検証."""
        cache = SimpleNamespace(name="cachedContents/abc", model="models/gemini-cache")

        with patch(
            "code_chat_cli.context_cache.ContextCache.resolve", return_value=cache
        ) as resolve:
            model, config = _resolve_cache_settings(
                MagicMock(), _cli_args(cache="abc", model="models/gemini-cache")
            )

        resolve.assert_called_once()
        assert model == "models/gemini-cache"
        assert config.cached_content == "cachedContents/abc"
        assert config.system_instruction is None

    def test_resolve_cache_settings_model_mismatch_success(self, caplog):
        """指定のモデルとキャッシュのモデルが異なる場合は, キャッシュのモデルが使われ, その旨がログに出るか検証."""
        cache = SimpleNamespace(name="cachedContents/abc", model="models/gemini-cache")

        with (
            caplog.at_level(logging.INFO),
            patch(
                "code_chat_cli.context_cache.ContextCache.resolve", return_value=cache
            ),
        ):
            model, _ = _resolve_cache_settings(
                MagicMock(), _cli_args(cache=True, model="gemini-other")
            )

        assert model == "models/gemini-cache"
        assert "キャッシュのモデルで実行します (指定: gemini-other)" in caplog.text

    def test_resolve_cache_settings_failure(self, caplog):
        """キャッシュを取得できない場合は, エラーを出力して終了コード 1 で終了するか検証."""
        with (
            patch(
                "code_chat_cli.context_cache.ContextCache.resolve",
                side_effect=CacheError("使用できるキャッシュがありません"),
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            _resolve_cache_settings(MagicMock(), _cli_args(cache=True))

        assert exc_info.value.code == 1
        assert "使用できるキャッシュがありません" in caplog.text


class TestCachedContentName:
    """`_cached_content_name` のテスト."""

    def test_cached_content_name_success(self):
        """解決済みのキャッシュ名 (文字列) が, そのまま返るか検証."""
        args = _cli_args(cache="cachedContents/abc")

        assert _cached_content_name(args) == "cachedContents/abc"

    @pytest.mark.parametrize("cache", [True, False])
    def test_cached_content_name_not_resolved(self, cache):
        """キャッシュ名が未解決 (フラグのみ) の場合は, None が返るか検証."""
        assert _cached_content_name(_cli_args(cache=cache)) is None


class TestHandleCacheSubcommand:
    """`_handle_cache_subcommand` のテスト."""

    @pytest.mark.parametrize(
        ("action", "handler", "expected_args"),
        [
            ("create", "create", ("gemini-flash-latest", "src", 120)),
            ("update", "update", ("gemini-flash-latest", "src")),
            ("rm", "remove", ("src",)),
            ("list", "list_caches", ()),
        ],
    )
    def test_handle_cache_subcommand_actions_success(
        self, action, handler, expected_args
    ):
        """cache の各アクションが対応するハンドラを呼び, 終了コード 0 で終了するか検証."""
        args = _cli_args(
            subcommand="cache",
            subcommand_action=action,
            subcommand_target="src",
            cache_ttl=120,
        )
        client = MagicMock()

        with (
            patch(
                f"code_chat_cli.context_cache.ContextCache.{handler}"
            ) as mock_handler,
            pytest.raises(SystemExit) as exc_info,
        ):
            _handle_cache_subcommand(client, args)

        mock_handler.assert_called_once_with(*expected_args)
        assert exc_info.value.code == 0

    def test_handle_cache_subcommand_default_target_success(self):
        """create の対象パスを省略した場合は, カレントディレクトリが対象になるか検証."""
        args = _cli_args(subcommand="cache", subcommand_action="create", cache_ttl=3600)

        with (
            patch("code_chat_cli.context_cache.ContextCache.create") as handler,
            pytest.raises(SystemExit),
        ):
            _handle_cache_subcommand(MagicMock(), args)

        assert handler.call_args.args[1] == "."

    def test_handle_cache_subcommand_unknown_action_failure(self, caplog):
        """不明なアクションは, 終了コード 1 で終了するか検証."""
        args = _cli_args(subcommand="cache", subcommand_action="unknown")

        with pytest.raises(SystemExit) as exc_info:
            _handle_cache_subcommand(MagicMock(), args)

        assert exc_info.value.code == 1
        assert "不明なサブコマンドアクション" in caplog.text

    def test_handle_cache_subcommand_cache_error_failure(self, caplog):
        """キャッシュの作成などに失敗した場合は, 原因を出力して終了コード 1 で終了するか検証."""
        args = _cli_args(subcommand="cache", subcommand_action="create")

        with (
            patch(
                "code_chat_cli.context_cache.ContextCache.create",
                side_effect=CacheError("無料枠では利用できません"),
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            _handle_cache_subcommand(MagicMock(), args)

        assert exc_info.value.code == 1
        assert "無料枠では利用できません" in caplog.text

    def test_handle_cache_subcommand_api_error_failure(self, caplog):
        """Gemini API のエラーが発生した場合は, ログを出力して終了コード 1 で終了するか検証."""
        args = _cli_args(subcommand="cache", subcommand_action="list")

        with (
            patch(
                "code_chat_cli.context_cache.ContextCache.list_caches",
                side_effect=APIError(500, {"error": {"message": "boom"}}),
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            _handle_cache_subcommand(MagicMock(), args)

        assert exc_info.value.code == 1
        assert "cache (list) コマンドの実行中にエラーが発生しました" in caplog.text

    def test_handle_cache_subcommand_unexpected_error_failure(self):
        """Gemini API 以外の予期しない例外は, 握りつぶさずに呼び出し元 (main) へ伝わるか検証."""
        args = _cli_args(subcommand="cache", subcommand_action="list")

        with (
            patch(
                "code_chat_cli.context_cache.ContextCache.list_caches",
                side_effect=RuntimeError("boom"),
            ),
            pytest.raises(RuntimeError, match="boom"),
        ):
            _handle_cache_subcommand(MagicMock(), args)


class TestRequireRagApiKey:
    """`_require_rag_api_key` のテスト."""

    @pytest.mark.parametrize("env_name", ["GEMINI_API_KEY", "GOOGLE_API_KEY"])
    def test_require_rag_api_key_success(self, monkeypatch, env_name):
        """GEMINI_API_KEY または GOOGLE_API_KEY のいずれかが設定されていれば, 何もせずに戻るか検証."""
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.setenv(env_name, "test-api-key")

        _require_rag_api_key()

    def test_require_rag_api_key_failure(self, monkeypatch, caplog):
        """API キーが未設定の場合, --oauth 指定時も API キーが必要な旨を出力して終了コード 1 で終了するか検証."""
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

        with pytest.raises(SystemExit) as exc_info:
            _require_rag_api_key()

        assert exc_info.value.code == 1
        assert "GEMINI_API_KEY" in caplog.text
        assert "--oauth" in caplog.text


class TestHandleLogin:
    """`_handle_login` のテスト."""

    def test_handle_login_success(self, capsys):
        """ログインに成功した場合, --oauth の指定を案内して終了コード 0 で終了するか検証."""
        with (
            patch("code_chat_cli.chat.login") as login,
            pytest.raises(SystemExit) as exc_info,
        ):
            _handle_login()

        login.assert_called_once_with()
        assert exc_info.value.code == 0
        assert "--oauth" in capsys.readouterr().out

    def test_handle_login_failure(self, capsys, caplog):
        """クライアント情報が未設定などでログインできない場合, メッセージを表示して終了コード 1 で終了するか検証."""
        with (
            patch(
                "code_chat_cli.chat.login",
                side_effect=OAuthError("OAuth ログインの設定がありません"),
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            _handle_login()

        assert exc_info.value.code == 1
        assert "OAuth ログインの設定がありません" in capsys.readouterr().err
        assert "ログインを実行できませんでした" in caplog.text


class TestHandleDryRun:
    """`_handle_dryrun` のテスト."""

    def test_handle_dryrun_success(self, capsys):
        """dry-run の出力に引数・生成設定・コンテキストのプレビューが含まれるか検証."""
        # ファイル・入力ディレクトリ・長いコンテキスト (400 文字) を指定
        args = _cli_args(
            files=["a.py", "b.py"],
            input_dirs=["src"],
            prompt="hello",
            context="x" * 400,
            subcommand="rag",
        )

        # 実行
        _handle_dryrun(args, _build_chat_config(False))

        # 各セクションが出力され, コンテキストは 300 文字で切り詰めて表示されること
        out = capsys.readouterr().out
        assert "[DRY-RUN]" in out
        assert "サブコマンド: rag" in out
        assert "    - a.py" in out
        assert "    - src" in out
        assert "プロンプト: hello" in out
        assert "コンテキスト長: 400 文字" in out
        assert "x" * 300 + "..." in out

    def test_handle_dryrun_minimal_args(self, capsys):
        """パスもコンテキストも無い場合の出力を検証."""
        # パス・入力ディレクトリ・コンテキストがすべて空の状態
        args = _cli_args(input_dirs=[], model="", provider="")

        # 実行 (Write モードの設定で出力)
        _handle_dryrun(args, _build_chat_config(True))

        out = capsys.readouterr().out
        # 未指定の項目は None と表示され, コンテキストのプレビューは出力されないこと
        assert "対象パス: None" in out
        assert "RAG 入力ディレクトリ: None" in out
        assert "収集されたコンテキストプレビュー" not in out


class TestHandleSubcommands:
    """`_handle_subcommands` のテスト."""

    def test_handle_subcommands_list_models_success(self):
        """--list-models が成功した場合, モデル一覧を表示して終了コード 0 で終了するか検証."""
        client = MagicMock()

        # モデル一覧の取得をモック化し, sys.exit を例外として受け取る
        with (
            patch("code_chat_cli.chat.handle_list_models") as handler,
            pytest.raises(SystemExit) as exc_info,
        ):
            _handle_subcommands(client, _cli_args(list_models=True))

        # クライアントを渡して一覧取得が呼ばれ, 正常終了 (終了コード 0) すること
        handler.assert_called_once_with(client)
        assert exc_info.value.code == 0

    def test_handle_subcommands_commit_msg_success(self):
        """--generate-commit-msg が成功時は終了コード 0 になるか検証."""
        # コミットメッセージ生成のフラグだけを指定
        args = _cli_args(generate_commit_msg=True)

        # 生成処理をモック化
        with (
            patch("code_chat_cli.chat.handle_commit_generation") as handler,
            pytest.raises(SystemExit) as exc_info,
        ):
            _handle_subcommands(MagicMock(), args)

        # 生成処理が呼ばれ, 正常終了すること
        handler.assert_called_once()
        assert exc_info.value.code == 0

    def test_handle_subcommands_rag_create_success(self) -> None:
        """rag create で正常終了する場合, handle_rag_create が呼ばれ sys.exit(0) されること."""
        # rag create + 入力/出力ディレクトリを指定
        cli_args = _cli_args(
            subcommand="rag",
            subcommand_action="create",
            input_dirs=["/path/to/repo"],
            output_dir="/path/to/db",
        )

        # rag create のハンドラをモック化
        with (
            patch("code_chat_cli.chat.handle_rag_create") as mock_handle,
            pytest.raises(SystemExit) as exc_info,
        ):
            _handle_subcommands(MagicMock(), cli_args)

        # 入力ディレクトリと出力先がハンドラに渡され, 正常終了すること
        mock_handle.assert_called_once_with(["/path/to/repo"], "/path/to/db")
        assert exc_info.value.code == 0

    def test_handle_subcommands_rag_prompt_success(self) -> None:
        """rag のアクション未指定でプロンプトがある場合, handle_rag が呼ばれ sys.exit(0) されること."""
        # アクションなし + プロンプトを指定 (ワンショット検索)
        cli_args = _cli_args(subcommand="rag", prompt="how to use this?")

        # RAG 検索のハンドラをモック化
        with (
            patch("code_chat_cli.chat.handle_rag") as mock_handle,
            pytest.raises(SystemExit) as exc_info,
        ):
            _handle_subcommands(MagicMock(), cli_args)

        # プロンプトが検索に渡され, 正常終了すること
        mock_handle.assert_called_once_with("how to use this?")
        assert exc_info.value.code == 0

    def test_handle_subcommands_dispatch_success(self):
        """rag / mcp / cache サブコマンドが振り分けられるか検証."""
        # rag は RAG サブコマンドの処理へ振り分けられる
        with patch("code_chat_cli.chat._handle_rag_subcommand") as rag:
            _handle_subcommands(MagicMock(), _cli_args(subcommand="rag"))
        rag.assert_called_once()

        # mcp は MCP サブコマンドの処理へ振り分けられる
        with patch("code_chat_cli.chat._handle_mcp_subcommand") as mcp:
            _handle_subcommands(MagicMock(), _cli_args(subcommand="mcp"))
        mcp.assert_called_once()

        # cache は cache サブコマンドの処理へ振り分けられる
        with patch("code_chat_cli.chat._handle_cache_subcommand") as cache:
            _handle_subcommands(MagicMock(), _cli_args(subcommand="cache"))
        cache.assert_called_once()

    def test_handle_subcommands_review_success(self):
        """--review が引数を渡して実行され, 終了コード 0 で終了するか検証."""
        client = MagicMock()
        # --review + --staged + ファイル指定
        args = _cli_args(review=True, staged=True, files=["a.py"])

        # コードレビューの実行をモック化
        with (
            patch("code_chat_cli.chat.handle_code_review") as handler,
            pytest.raises(SystemExit) as exc_info,
        ):
            _handle_subcommands(client, args)

        # --staged とファイル指定がレビュー処理に渡され, 正常終了すること
        handler.assert_called_once_with(
            client, args.model, staged=True, file_path=["a.py"]
        )
        assert exc_info.value.code == 0

    @pytest.mark.parametrize(
        "error",
        [
            APIError(500, {"error": {"message": "boom"}}),
            subprocess.CalledProcessError(128, ["git", "diff"]),
            FileNotFoundError("git"),
        ],
    )
    def test_handle_subcommands_commit_msg_failure(self, error, caplog):
        """--generate-commit-msg で Gemini API・git のエラーが発生した場合, ログを出力して終了コード 1 で終了するか検証."""
        with (
            patch("code_chat_cli.chat.handle_commit_generation", side_effect=error),
            pytest.raises(SystemExit) as exc_info,
        ):
            _handle_subcommands(MagicMock(), _cli_args(generate_commit_msg=True))

        assert exc_info.value.code == 1
        assert "generate_commit_msg" in caplog.text

    def test_handle_subcommands_list_models_failure(self):
        """--list-models の実行中に例外が発生した場合, 終了コード 1 で終了するか検証."""
        # モデル一覧の取得で例外を発生させる
        with (
            patch(
                "code_chat_cli.chat.handle_list_models",
                side_effect=APIError(500, {"error": {"message": "boom"}}),
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            _handle_subcommands(MagicMock(), _cli_args(list_models=True))

        # 例外は握りつぶされ, 終了コード 1 で終了すること
        assert exc_info.value.code == 1

    def test_handle_subcommands_rag_create_failure(self) -> None:
        """rag create 実行時に例外が発生した場合, sys.exit(1) されること."""
        cli_args = _cli_args(subcommand="rag", subcommand_action="create")

        # ハンドラが例外を送出する設定
        with (
            patch(
                "code_chat_cli.chat.handle_rag_create",
                side_effect=RuntimeError("Index failure"),
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            _handle_subcommands(MagicMock(), cli_args)

        # 例外時は終了コード 1 で終了すること
        assert exc_info.value.code == 1

    def test_handle_subcommands_rag_prompt_failure(self) -> None:
        """rag のプロンプト検索で例外が発生した場合, sys.exit(1) されること."""
        cli_args = _cli_args(subcommand="rag", prompt="how to use this?")

        # 検索ハンドラが例外を送出する設定
        with (
            patch(
                "code_chat_cli.chat.handle_rag",
                side_effect=RuntimeError("Ask failure"),
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            _handle_subcommands(MagicMock(), cli_args)

        # 例外時は終了コード 1 で終了すること
        assert exc_info.value.code == 1

    def test_handle_subcommands_review_failure(self):
        """--review の実行中に例外が発生した場合, 終了コード 1 で終了するか検証."""
        # レビュー処理で例外を発生させる
        with (
            patch(
                "code_chat_cli.chat.handle_code_review",
                side_effect=APIError(500, {"error": {"message": "boom"}}),
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            _handle_subcommands(MagicMock(), _cli_args(review=True))

        # 例外は握りつぶされ, 終了コード 1 で終了すること
        assert exc_info.value.code == 1

    def test_handle_subcommands_no_subcommand(self) -> None:
        """サブコマンドが指定されていない場合, 処理をスキップすること."""
        mock_client = MagicMock()
        mock_args = _cli_args()

        # sys.exit が呼ばれずに正常終了することを確認
        _handle_subcommands(mock_client, mock_args)


class TestHandleRagSubcommand:
    """`_handle_rag_subcommand` のテスト."""

    @pytest.mark.parametrize(
        ("action", "handler", "expected_args"),
        [
            ("create", "handle_rag_create", (["a"], "db")),
            ("update", "handle_rag_update", (["a"], "db")),
            ("rm", "handle_rag_rm", ("db",)),
            ("status", "handle_rag_status", (["a"], "db")),
        ],
    )
    def test_handle_rag_subcommand_actions_success(
        self, action, handler, expected_args
    ):
        """rag の各アクションが対応するハンドラを呼び, 正常終了するか検証."""
        # アクションごとに, 入力/出力ディレクトリを指定
        args = _cli_args(
            subcommand="rag",
            subcommand_action=action,
            input_dirs=["a"],
            output_dir="db",
        )

        # 対象アクションのハンドラだけをモック化
        with (
            patch(f"code_chat_cli.chat.{handler}") as mock_handler,
            pytest.raises(SystemExit) as exc_info,
        ):
            _handle_rag_subcommand(args)

        # アクションに対応するハンドラが引数付きで呼ばれ, 正常終了すること
        mock_handler.assert_called_once_with(*expected_args)
        assert exc_info.value.code == 0

    def test_handle_rag_subcommand_prompt_list_success(self):
        """プロンプトがリストの場合は結合されて検索されるか検証."""
        args = _cli_args(subcommand="rag")
        # プロンプトが単語のリストで渡された場合を再現
        args.prompt = ["how", "to"]

        with (
            patch("code_chat_cli.chat.handle_rag") as handler,
            pytest.raises(SystemExit) as exc_info,
        ):
            _handle_rag_subcommand(args)

        # 空白区切りで結合した文字列で検索されること
        handler.assert_called_once_with("how to")
        assert exc_info.value.code == 0

    def test_handle_rag_subcommand_no_action_no_prompt(self):
        """アクションもプロンプトも無い場合は何もせずに戻るか検証."""
        # アクションもプロンプトも無い場合は, sys.exit せず例外なく戻ること
        _handle_rag_subcommand(_cli_args(subcommand="rag", prompt=""))


class TestHandleMcpSubcommand:
    """`_handle_mcp_subcommand` のテスト."""

    @pytest.mark.parametrize(
        ("action", "target"),
        [("status", "handle_mcp_status"), ("test", "handle_mcp_test")],
    )
    def test_handle_mcp_subcommand_actions_success(self, action, target):
        """mcp status / test が対応するハンドラを呼び, 正常終了するか検証."""
        # status / test のアクションを指定
        args = _cli_args(subcommand="mcp", subcommand_action=action)

        # 対象アクションのハンドラだけをモック化
        with (
            patch(f"code_chat_cli.chat.{target}") as handler,
            pytest.raises(SystemExit) as exc_info,
        ):
            _handle_mcp_subcommand(args)

        # 設定パス未指定 (None) でハンドラが呼ばれ, 正常終了すること
        handler.assert_called_once_with(config_path=None)
        assert exc_info.value.code == 0

    def test_handle_mcp_subcommand_unknown_action_failure(self):
        """不明なアクションは終了コード 1 になるか検証."""
        # 未対応のアクション名を指定
        with pytest.raises(SystemExit) as exc_info:
            _handle_mcp_subcommand(_cli_args(subcommand="mcp", subcommand_action="x"))

        # エラーを記録し, 終了コード 1 で終了すること
        assert exc_info.value.code == 1

    def test_handle_mcp_subcommand_handler_failure(self):
        """ハンドラが例外を送出した場合は終了コード 1 になるか検証."""
        # status アクションを指定
        args = _cli_args(subcommand="mcp", subcommand_action="status")

        # ハンドラで例外を発生させる
        with (
            patch(
                "code_chat_cli.chat.handle_mcp_status", side_effect=RuntimeError("x")
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            _handle_mcp_subcommand(args)

        # 例外は握りつぶされ, 終了コード 1 で終了すること
        assert exc_info.value.code == 1


class TestBuildChatConfig:
    """`_build_chat_config` のテスト."""

    def test_build_chat_config_success(self):
        """通常時は, システム指示が設定され, キャッシュは指定されないか検証."""
        config = _build_chat_config(False)

        assert config.system_instruction
        assert config.cached_content is None

    def test_build_chat_config_write_mode_success(self):
        """Write モード時は, Write モード用のシステム指示と低い temperature が設定されるか検証."""
        config = _build_chat_config(True)

        assert config.temperature == 0.1
        assert "コード" in config.system_instruction

    def test_build_chat_config_cached_content_success(self):
        """キャッシュ指定時は, キャッシュ名が設定され, システム指示は指定されない (キャッシュ側に含める) か検証."""
        config = _build_chat_config(False, cached_content="cachedContents/abc")

        assert config.cached_content == "cachedContents/abc"
        assert config.system_instruction is None


class TestHandleMcpSingleTurn:
    """`_handle_mcp_single_turn` のテスト."""

    def test_handle_mcp_single_turn_context_success(self, capsys):
        """プロンプトが無い場合は context が使われ, 結果が出力されるか検証."""
        # プロンプトが空で, context だけを指定
        args = _cli_args(mcp=True, prompt="", context="ctx text")

        # MCP の実行をモック化
        with patch(
            "code_chat_cli.chat.handle_mcp_run", new=AsyncMock(return_value="answer")
        ) as run:
            _handle_mcp_single_turn(args, [])

        # context がプロンプトとして MCP に渡され, 結果が標準出力に出ること
        assert run.await_args.kwargs["user_prompt"] == "ctx text"
        assert "answer" in capsys.readouterr().out

    def test_handle_mcp_single_turn_rag_success(self):
        """RAG サービスがある場合は, 検索したコンテキストが付加されたプロンプトが MCP に渡され, 履歴には元のプロンプトだけが残るか検証."""
        args = _cli_args(mcp=True, prompt="q")
        rag_service = MagicMock()
        rag_service.get_context.return_value = "rag-ctx"
        history: list[str] = []

        with patch(
            "code_chat_cli.chat.handle_mcp_run", new=AsyncMock(return_value="answer")
        ) as run:
            _handle_mcp_single_turn(args, history, rag_service)

        sent = run.await_args.kwargs["user_prompt"]
        assert sent.startswith("q")
        assert "rag-ctx" in sent
        assert history[0] == "### User (MCP)\n\nq"

    def test_handle_mcp_single_turn_oauth_success(self):
        """--oauth 指定時は, OAuth で認証する指定が MCP に引き継がれるか検証."""
        args = _cli_args(mcp=True, prompt="q", oauth=True)

        with patch(
            "code_chat_cli.chat.handle_mcp_run", new=AsyncMock(return_value="answer")
        ) as run:
            _handle_mcp_single_turn(args, [])

        assert run.await_args.kwargs["use_oauth"] is True

    def test_handle_mcp_single_turn_cache_success(self):
        """解決済みのモデルとキャッシュ名が, MCP に引き継がれるか検証."""
        args = _cli_args(
            mcp=True,
            prompt="q",
            model="models/gemini-cache",
            cache="cachedContents/abc",
        )

        with patch(
            "code_chat_cli.chat.handle_mcp_run", new=AsyncMock(return_value="answer")
        ) as run:
            _handle_mcp_single_turn(args, [])

        assert run.await_args.kwargs["model_name"] == "models/gemini-cache"
        assert run.await_args.kwargs["cached_content"] == "cachedContents/abc"

    def test_handle_mcp_single_turn_no_input_failure(self, caplog):
        """プロンプトも context も無い場合はエラーを記録して何もしないか検証."""
        history: list[str] = []

        # プロンプトも context も空の状態で実行
        _handle_mcp_single_turn(_cli_args(mcp=True, prompt="", context=""), history)

        # MCP は実行されず, エラーログだけが残り, 履歴も増えないこと
        assert (
            "MCP 実行用のプロンプトまたはコンテキストを指定してください" in caplog.text
        )
        assert not history

    def test_handle_mcp_single_turn_api_error_exception(self, caplog):
        """MCP 実行中の Gemini API のエラーは, 概要とヒントに整理されて記録されるか検証."""
        args = _cli_args(mcp=True, prompt="q")

        with patch(
            "code_chat_cli.chat.handle_mcp_run",
            new=AsyncMock(
                side_effect=APIError(
                    503, {"error": {"message": "high demand", "status": "UNAVAILABLE"}}
                )
            ),
        ):
            _handle_mcp_single_turn(args, [])

        assert "[HTTP 503 UNAVAILABLE]" in caplog.text
        assert "ヒント: " in caplog.text
        assert "'error'" not in caplog.text

    def test_handle_mcp_single_turn_exception(self, caplog):
        """MCP 実行が失敗した場合はエラーを記録し, 履歴に応答を残さないか検証."""
        history: list[str] = []

        # MCP の実行で例外を発生させる
        with patch(
            "code_chat_cli.chat.handle_mcp_run",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            _handle_mcp_single_turn(_cli_args(mcp=True, prompt="q"), history)

        # エラーがログに残り, 履歴には User 側だけが記録されること
        assert "MCP クエリの実行中にエラーが発生しました: boom" in caplog.text
        assert history == ["### User (MCP)\n\nq"]


class TestHandleMcpInteractive:
    """`_handle_mcp_interactive` のテスト."""

    def test_handle_mcp_interactive_slash_prefix_success(self, capsys):
        """/mcp プレフィックスが除去されて MCP に渡されるか検証."""
        history: list[str] = []

        # MCP の実行をモック化
        with patch(
            "code_chat_cli.chat.handle_mcp_run", new=AsyncMock(return_value="ok")
        ) as run:
            _handle_mcp_interactive("/mcp git status", _cli_args(), history)

        # /mcp を除いたプロンプトが MCP に渡され, 応答が出力と履歴に記録されること
        assert run.await_args.kwargs["user_prompt"] == "git status"
        assert "ok" in capsys.readouterr().out
        assert history[-1] == "### Gemini (MCP)\n\nok"

    def test_handle_mcp_interactive_rag_success(self):
        """RAG サービスがある場合は, 検索したコンテキストが付加されたプロンプトが MCP に渡され, 履歴には元のプロンプトだけが残るか検証."""
        rag_service = MagicMock()
        rag_service.get_context.return_value = "rag-ctx"
        history: list[str] = []

        with patch(
            "code_chat_cli.chat.handle_mcp_run", new=AsyncMock(return_value="ok")
        ) as run:
            _handle_mcp_interactive(
                "/mcp git status", _cli_args(), history, rag_service
            )

        sent = run.await_args.kwargs["user_prompt"]
        assert sent.startswith("git status")
        assert "rag-ctx" in sent
        assert history[0] == "### User (MCP)\n\ngit status"

    def test_handle_mcp_interactive_oauth_success(self):
        """--oauth 指定時は, OAuth で認証する指定が MCP に引き継がれるか検証."""
        with patch(
            "code_chat_cli.chat.handle_mcp_run", new=AsyncMock(return_value="ok")
        ) as run:
            _handle_mcp_interactive("/mcp x", _cli_args(oauth=True), [])

        assert run.await_args.kwargs["use_oauth"] is True

    def test_handle_mcp_interactive_mcp_mode_success(self):
        """--mcp モードではプレフィックスの無い入力もそのまま MCP に渡されるか検証."""
        # --mcp モードで, /mcp の付かない入力を渡す
        with patch(
            "code_chat_cli.chat.handle_mcp_run", new=AsyncMock(return_value="ok")
        ) as run:
            _handle_mcp_interactive("hello", _cli_args(mcp=True), [])

        # 入力がそのままプロンプトとして渡されること
        assert run.await_args.kwargs["user_prompt"] == "hello"

    def test_handle_mcp_interactive_empty_prompt_failure(self, caplog):
        """/mcp のみでプロンプトが空の場合はエラーを記録するか検証."""
        # /mcp の後ろが空白だけの入力
        with patch("code_chat_cli.chat.handle_mcp_run", new=AsyncMock()) as run:
            _handle_mcp_interactive("/mcp   ", _cli_args(), [])

        # MCP は実行されず, エラーログが残ること
        run.assert_not_awaited()
        assert "実行する MCP プロンプトを指定してください" in caplog.text

    def test_handle_mcp_interactive_exception(self, caplog):
        """MCP 実行が失敗した場合はエラーを記録するか検証."""
        # MCP の実行で例外を発生させる
        with patch(
            "code_chat_cli.chat.handle_mcp_run",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            _handle_mcp_interactive("/mcp x", _cli_args(), [])

        # エラーがログに残ること
        assert "MCP クエリの実行中にエラーが発生しました: boom" in caplog.text


class TestMain:
    """`main` のテスト."""

    def test_main_write_mode_system_instruction_success(
        self, monkeypatch, mock_gemini_client, mock_args
    ):
        """write_mode が True の場合, system_instruction に Write Mode 用の指示が追加されるか検証."""
        # write_mode を True に設定
        mock_args.return_value.write_mode = True
        mock_args.return_value.prompt = "コードを修正してください"

        # 対話ループに入っても, 最初の input() で exit を返して終了させる
        inputs = iter(["exit"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))

        main()

        # Client または chats.create の呼び出し引数を検証
        assert mock_gemini_client["client"].chats.create.call_count == 1
        _, kwargs = mock_gemini_client["client"].chats.create.call_args

        config = kwargs.get("config")
        system_instruction = config.system_instruction if config else ""

        # Write Mode の最重要ルールが含まれているかチェック
        assert "【厳格な遵守事項】" in system_instruction
        assert (
            "1. Markdown のコードブロック記号（```python や ```）を含めないでください."
            in system_instruction
        )
        assert (
            "2. 挨拶, 解説, 説明文, 前置き, 後書きは一切含めないでください."
            in system_instruction
        )
        assert (
            "3. 出力の1文字目から最後の文字まで, すべてPythonソースコードとして直接実行可能なテキストのみを出力してください."
            in system_instruction
        )

    def test_main_dryrun_success(self, mock_args):
        """--dry-run では API クライアントを作らずに終了コード 0 で終了するか検証."""
        # --dry-run を指定
        mock_args.return_value.dryrun = True

        # API クライアントの生成をモック化し, 呼ばれないことを確認する
        with (
            patch("code_chat_cli.chat.get_gemini_client") as get_client,
            pytest.raises(SystemExit) as exc_info,
        ):
            main()

        # クライアントを作らず, 終了コード 0 で終了すること
        get_client.assert_not_called()
        assert exc_info.value.code == 0

    @pytest.mark.parametrize(
        ("action", "handler"),
        [("create", "handle_rag_create"), ("update", "handle_rag_update")],
    )
    def test_main_dryrun_rag_index_success(self, mock_args, action, handler):
        """`rag create` / `rag update` の --dry-run では, dryrun=True で対象ファイル一覧を表示し, クライアントを作らないか検証."""
        mock_args.return_value.dryrun = True
        mock_args.return_value.subcommand = "rag"
        mock_args.return_value.subcommand_action = action

        with (
            patch("code_chat_cli.chat.get_gemini_client") as get_client,
            patch(f"code_chat_cli.chat.{handler}") as mock_handler,
            pytest.raises(SystemExit) as exc_info,
        ):
            main()

        get_client.assert_not_called()
        mock_handler.assert_called_once_with(["."], "./.chroma_db", dryrun=True)
        assert exc_info.value.code == 0

    def test_main_dryrun_rag_other_action_success(self, mock_args):
        """`rag status` の --dry-run では, インデックスの一覧表示を行わないか検証."""
        mock_args.return_value.dryrun = True
        mock_args.return_value.subcommand = "rag"
        mock_args.return_value.subcommand_action = "status"

        with (
            patch("code_chat_cli.chat.handle_rag_create") as mock_create,
            patch("code_chat_cli.chat.handle_rag_update") as mock_update,
            pytest.raises(SystemExit) as exc_info,
        ):
            main()

        mock_create.assert_not_called()
        mock_update.assert_not_called()
        assert exc_info.value.code == 0

    def test_main_login_success(self, mock_args, mock_gemini_client):
        """--login ではログインだけを行い, API クライアントを作らずに終了コード 0 で終了するか検証."""
        mock_args.return_value.login = True

        with (
            patch("code_chat_cli.chat.login") as login,
            pytest.raises(SystemExit) as exc_info,
        ):
            main()

        login.assert_called_once_with()
        mock_gemini_client["get_client"].assert_not_called()
        assert exc_info.value.code == 0

    def test_main_oauth_success(self, mock_args, mock_gemini_client):
        """--oauth 指定時は, OAuth で認証するようにクライアントを作成するか検証."""
        mock_args.return_value.oauth = True
        mock_args.return_value.prompt = "hello"

        main()

        mock_gemini_client["get_client"].assert_called_once_with(use_oauth=True)

    def test_main_cache_success(self, mock_args, mock_gemini_client):
        """-c 指定時は, キャッシュのモデルとキャッシュ名を指定してチャットが作成されるか検証."""
        mock_args.return_value.cache = True
        mock_args.return_value.prompt = "q"
        cache = SimpleNamespace(name="cachedContents/abc", model="models/gemini-cache")
        mock_gemini_client["chat"].send_message_stream.return_value = [_chunk("reply")]

        with patch(
            "code_chat_cli.context_cache.ContextCache.resolve", return_value=cache
        ):
            main()

        kwargs = mock_gemini_client["client"].chats.create.call_args.kwargs
        assert kwargs["model"] == "models/gemini-cache"
        assert kwargs["config"].cached_content == "cachedContents/abc"

    @pytest.mark.usefixtures("mock_gemini_client")
    def test_main_cache_mcp_success(self, mock_args):
        """-c と --mcp の併用時は, 引数のエラーにせず, キャッシュのモデルとキャッシュ名が MCP に渡されるか検証."""
        mock_args.return_value.cache = True
        mock_args.return_value.mcp = True
        mock_args.return_value.prompt = "q"
        cache = SimpleNamespace(name="cachedContents/abc", model="models/gemini-cache")

        with (
            patch(
                "code_chat_cli.context_cache.ContextCache.resolve", return_value=cache
            ),
            patch(
                "code_chat_cli.chat.handle_mcp_run",
                new=AsyncMock(return_value="mcp-answer"),
            ) as run,
        ):
            main()

        assert run.await_args.kwargs["model_name"] == "models/gemini-cache"
        assert run.await_args.kwargs["cached_content"] == "cachedContents/abc"

    def test_main_rag_success(self, monkeypatch, mock_args, mock_gemini_client):
        """--rag 指定時に RagService が初期化され, 応答に反映されるか検証."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-api-key")
        # RAG 有効 + プロンプトのワンショット実行
        mock_args.return_value.rag = True
        mock_args.return_value.prompt = "how does it work?"
        mock_args.return_value.input_dirs = ["src"]
        mock_args.return_value.output_dir = "db"
        mock_gemini_client["chat"].send_message_stream.return_value = [_chunk("reply")]

        # RagService をモック化 (実際の DB や Embedding API は使わない)
        with patch("code_chat_cli.chat.RagService") as rag_cls:
            rag_cls.return_value.get_context.return_value = "rag-ctx"
            main()

        # 指定ディレクトリで RagService が初期化され, 取得したコンテキストが送信されること
        rag_cls.assert_called_once_with(input_dirs=["src"], output_dir="db")
        sent = mock_gemini_client["chat"].send_message_stream.call_args[0][0]
        assert "rag-ctx" in sent

    @pytest.mark.usefixtures("mock_gemini_client")
    def test_main_rag_mcp_success(self, monkeypatch, mock_args):
        """--rag と --mcp の併用時に, RAG で取得したコンテキストが MCP のプロンプトに付加されるか検証."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-api-key")
        mock_args.return_value.rag = True
        mock_args.return_value.mcp = True
        mock_args.return_value.oauth = True
        mock_args.return_value.prompt = "how does it work?"

        with (
            patch("code_chat_cli.chat.RagService") as rag_cls,
            patch(
                "code_chat_cli.chat.handle_mcp_run",
                new=AsyncMock(return_value="mcp-answer"),
            ) as run,
        ):
            rag_cls.return_value.get_context.return_value = "rag-ctx"
            main()

        # RAG のコンテキストが付加されたプロンプトが, OAuth 指定のまま MCP に渡されること
        kwargs = run.await_args.kwargs
        assert "how does it work?" in kwargs["user_prompt"]
        assert "rag-ctx" in kwargs["user_prompt"]
        assert kwargs["use_oauth"] is True

    def test_main_auto_save_success(self, monkeypatch, mock_gemini_client, mock_args):
        """auto_save=True の時, タイムスタンプ形式のファイル名で自動保存されるか検証."""
        mock_args.return_value.context = None
        mock_args.return_value.prompt = "こんにちは"
        mock_args.return_value.auto_save = True

        # レスポンスのモック
        mock_chunk = SimpleNamespace(text=" Gemini です.")
        mock_gemini_client["chat"].send_message_stream.return_value = [mock_chunk]

        # 対話ループをすぐに抜けるため exit を返却
        inputs = iter(["exit"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))

        with patch("code_chat_cli.history.save_chat_history") as mock_save:
            main()

            # save_chat_history が呼び出されたか検証
            mock_save.assert_called_once()
            saved_file_path = mock_save.call_args[0][0]

            # タイムスタンプ形式 (_chat.md) のファイル名で保存されているか確認
            assert saved_file_path.endswith("_chat.md")

    def test_main_list_models_success(
        self, monkeypatch, mock_gemini_client, mock_args, capsys
    ):
        """--list-models 指定時にモデル一覧を表示して正常終了するか検証."""
        mock_args.return_value.list_models = True

        # モデルのモックを作成（SimpleNamespace を使用）
        mock_model = SimpleNamespace(
            name="models/gemini-flash-latest",
            display_name="Gemini Flash Latest",
            supported_actions=["generateContent"],
            supported_generation_methods=["generateContent"],
        )

        # models.list() の戻り値としてモックのリストを設定
        mock_gemini_client["client"].models.list.return_value = [mock_model]

        monkeypatch.setattr("sys.argv", ["chat.py", "--list-models"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()

        # 期待するモデル名が出力に含まれているか検証
        assert "- gemini-flash-latest (Gemini Flash Latest)" in captured.out

    def test_main_generate_commit_msg_success(
        self,
        mock_client: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """CLI 経由で handle_commit_generation が適切に呼び出されることを検証する."""
        test_args = ["chat.py", "--generate-commit-msg"]
        monkeypatch.setattr("sys.argv", test_args)

        mock_args = _cli_args(generate_commit_msg=True)

        with (
            patch("code_chat_cli.chat.parse_args", return_value=mock_args),
            patch(
                "code_chat_cli.chat.get_gemini_client",
                return_value=mock_client,
            ),
            # コミットメッセージ生成の呼び出しをモック化 (chat.py が参照する名前を差し替える)
            patch("code_chat_cli.chat.handle_commit_generation") as mock_handle,
            pytest.raises(SystemExit) as exc_info,
        ):
            main()

        # 生成処理が 1 回呼ばれ, 正常終了すること
        assert exc_info.value.code == 0
        mock_handle.assert_called_once()

    @pytest.mark.usefixtures("mock_gemini_client")
    def test_main_rag_without_api_key_failure(self, monkeypatch, mock_args):
        """--rag 指定時に API キーが無い場合, RagService を作らずに終了コード 1 で終了するか検証."""
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        mock_args.return_value.rag = True
        mock_args.return_value.oauth = True
        mock_args.return_value.prompt = "q"

        with (
            patch("code_chat_cli.chat.RagService") as rag_cls,
            pytest.raises(SystemExit) as exc_info,
        ):
            main()

        assert exc_info.value.code == 1
        rag_cls.assert_not_called()

    def test_main_generate_commit_msg_failure(self):
        """-g オプション実行時にエラーが発生した場合, exit(1) で終了するか検証."""
        test_args = ["code_chat_cli", "-g"]

        with (
            patch.object(sys, "argv", test_args),
            patch("code_chat_cli.chat.parse_args") as mock_parse_args,
        ):
            # -g を指定し, 生成処理が例外を送出する設定
            mock_cli_args = _cli_args(generate_commit_msg=True)
            mock_parse_args.return_value = mock_cli_args

            with patch(
                "code_chat_cli.chat.handle_commit_generation",
                side_effect=RuntimeError("API Failure"),
            ):
                with pytest.raises(SystemExit) as exc_info:
                    main()

                # 例外時は終了コード 1 で終了すること
                assert exc_info.value.code == 1

    def test_main_list_models_failure(self, monkeypatch, mock_gemini_client, mock_args):
        """--list-models 指定時に API エラー等の例外が発生した場合, sys.exit(1) で終了するか検証."""
        mock_args.return_value.list_models = True

        # models.list() 呼び出し時に Exception を発生させる
        mock_gemini_client["client"].models.list.side_effect = Exception(
            "API connection error"
        )

        monkeypatch.setattr("sys.argv", ["chat.py", "--list-models"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        # ステータスコード 1 で終了したことを検証
        assert exc_info.value.code == 1

    def test_main_api_error_failure(self, monkeypatch, mock_gemini_client):
        """API 送信時に APIError が発生した場合, sys.exit(1) で終了するか検証."""
        # 送信時に, リトライ対象外の API エラー (400) を発生させる
        mock_gemini_client["chat"].send_message_stream.side_effect = APIError(
            400, {"error": {"message": "Bad request"}}
        )

        # 対話モードで 1 回メッセージを入力する
        user_input = "エラーテスト\nexit\n"
        monkeypatch.setattr("sys.stdin", io.StringIO(user_input))
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("sys.argv", ["chat.py"])

        # 実行 (待機が発生しないよう, スリープをスキップする)
        with (
            patch("code_chat_cli.chat.time.sleep"),
            pytest.raises(SystemExit) as exc_info,
        ):
            main()

        # API エラーは捕捉され, 終了コード 1 で終了すること
        assert exc_info.value.code == 1

    def test_main_api_error_summary_failure(
        self, monkeypatch, mock_gemini_client, caplog
    ):
        """Gemini API のエラーは, 辞書の全文ではなく, 概要とヒントだけがトレースバックなしで 1 回出力されるか検証."""
        mock_gemini_client["chat"].send_message_stream.side_effect = APIError(
            400,
            {"error": {"message": "API key not valid", "status": "INVALID_ARGUMENT"}},
        )
        monkeypatch.setattr("sys.stdin", io.StringIO("テスト\nexit\n"))
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("sys.argv", ["chat.py"])

        # ログ設定 (ルートのハンドラの入れ替え) を避け, caplog で記録を検証する
        with (
            patch("code_chat_cli.chat._setup_cli_logging"),
            pytest.raises(SystemExit),
        ):
            main()

        messages = [
            r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR
        ]
        assert len(messages) == 1
        assert (
            "Gemini API エラーにより処理を中断しました: [HTTP 400 INVALID_ARGUMENT]"
            in messages[0]
        )
        assert "API キーが無効です" in messages[0]
        assert "ヒント: " in messages[0]
        assert caplog.records[-1].exc_info is None

    def test_main_file_not_found_summary_failure(self, monkeypatch, mock_args, caplog):
        """FileNotFoundError は, トレースバックなしの概要 1 行を出力し, sys.exit(1) で終了するか検証."""
        mock_args.side_effect = FileNotFoundError("指定されたファイルが見つかりません")
        monkeypatch.setattr("sys.argv", ["chat.py"])

        with (
            patch("code_chat_cli.chat._setup_cli_logging"),
            pytest.raises(SystemExit) as exc_info,
        ):
            main()

        assert exc_info.value.code == 1
        messages = [
            r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR
        ]
        assert messages == [
            "ファイルまたはディレクトリが見つかりません: 指定されたファイルが見つかりません"
        ]
        assert all(
            r.exc_info is None for r in caplog.records if r.levelno >= logging.ERROR
        )

    @pytest.mark.parametrize(
        "file_exception",
        [
            ValueError("無効なファイルパスです"),
            PermissionError("ファイルの読み込み権限がありません"),
        ],
    )
    def test_main_file_operation_failure(self, monkeypatch, mock_args, file_exception):
        """ファイル操作関連の例外 (ValueError, PermissionError) 発生時に sys.exit(1) で終了するか検証."""
        # parse_args 呼び出し時（またはファイル操作処理時）に指定の例外を発生させる
        mock_args.side_effect = file_exception

        monkeypatch.setattr("sys.argv", ["chat.py"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        # ステータスコード 1 で終了したことを検証
        assert exc_info.value.code == 1

    def test_main_unexpected_exception_failure(self, monkeypatch, mock_args):
        """main() 実行中に予期せぬ例外が発生した場合, logger.critical を経由して sys.exit(1) で終了するか検証."""
        # parse_args の段階で意図的に予期せぬ例外を発生させる
        mock_args.side_effect = RuntimeError("Unexpected fatal system error")

        monkeypatch.setattr("sys.argv", ["chat.py"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        # ステータスコード 1 で終了したことを検証
        assert exc_info.value.code == 1

    def test_main_unexpected_exception_logging_failure(self, caplog):
        """予期せぬ例外が発生した際, 例外の内容がログに出力され, sys.exit(1) で終了するか検証."""
        test_args = ["code_chat_cli"]

        # parse_args で予期せぬ例外を発生させる
        with (
            patch.object(sys, "argv", test_args),
            patch(
                "code_chat_cli.chat.parse_args",
                side_effect=Exception("Fatal Boom"),
            ),
        ):
            with pytest.raises(SystemExit) as exc_info:
                main()

            # 終了コード 1 で終了し, 例外の内容がログに出力されること
            assert exc_info.value.code == 1
            assert "予期せぬエラーが発生しました: Fatal Boom" in caplog.text

    @pytest.mark.parametrize(
        ("log_level", "has_traceback"),
        [(logging.DEBUG, True), (logging.INFO, False)],
        ids=["debug", "info"],
    )
    def test_main_unexpected_exception_traceback_failure(
        self, caplog, log_level, has_traceback
    ):
        """予期せぬ例外のログに, debug ログが有効なときだけトレースバックが付くか検証."""
        # ログレベルを切り替えて, logger.isEnabledFor(DEBUG) の結果を変える
        caplog.set_level(log_level, logger="code_chat_cli.chat")

        # parse_args で予期せぬ例外を発生させる
        with (
            patch.object(sys, "argv", ["code_chat_cli"]),
            patch(
                "code_chat_cli.chat.parse_args",
                side_effect=Exception("Fatal Boom"),
            ),
            pytest.raises(SystemExit) as exc_info,
        ):
            main()

        assert exc_info.value.code == 1

        # debug 有効時だけ exc_info (トレースバック) が付き, 無効時は付かないこと
        record = next(
            r
            for r in caplog.records
            if "予期せぬエラーが発生しました" in r.getMessage()
        )
        assert bool(record.exc_info) is has_traceback
        if has_traceback:
            assert record.exc_info[1].args == ("Fatal Boom",)

    @pytest.mark.parametrize("exception_type", [KeyboardInterrupt, EOFError])
    def test_main_interrupt_exception(
        self,
        exception_type: type[BaseException],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """_run_interactive_loop 実行時に KeyboardInterrupt や EOFError が発生した際,
           except ブロックを通って sys.exit(0) で正常終了することを検証する.

        Args:
            exception_type (type[BaseException]): 送出させる例外クラス.
            monkeypatch (pytest.MonkeyPatch): pytest のモックフィクスチャ.
        """
        # 最小限の引数設定
        test_args = ["chat.py"]
        monkeypatch.setattr("sys.argv", test_args)

        # CLI 引数のモック
        mock_args = _cli_args()

        # 各モックの適用
        with (
            patch("code_chat_cli.chat.parse_args", return_value=mock_args),
            patch("code_chat_cli.chat._setup_cli_logging"),
            patch("code_chat_cli.chat.get_gemini_client"),
            patch("code_chat_cli.chat._handle_subcommands"),
            patch("code_chat_cli.chat._build_chat_config"),
            # _run_interactive_loop が呼び出された際に指定の例外を送出させる
            patch(
                "code_chat_cli.chat._run_interactive_loop",
                side_effect=exception_type,
            ),
            patch("code_chat_cli.chat.save_history_if_needed"),
            pytest.raises(SystemExit) as exc_info,
        ):
            main()

        # sys.exit(0) で正常終了したことを検証
        assert exc_info.value.code == 0
        assert "[Ctrl+C] 会話を終了します" in capsys.readouterr().out
