"""Gemini API を使用してローカルコードの参照・対話を行うCLIチャットツール.

このモジュールは, 指定されたファイルやパイプ入力をコンテキストとして読み込み,
Gemini API と対話を行うためのコマンドラインインターフェースを提供します.
ファイルの上書き保存機能や会話ログの自動保存機能を含みます.
"""

import asyncio
import atexit
import logging
import os
import sys
import time  # pylint: disable=unused-import # noqa: F401
from pathlib import Path  # pylint: disable=unused-import
from typing import Any

from code_chat_rag.rag_service import RagService
from google.genai import types
from google.genai.errors import APIError, ClientError, ServerError

from code_chat_cli.api import (
    send_message_stream_with_retry,
    send_message_with_retry,
)
from code_chat_cli.args import parse_args
from code_chat_cli.auth import OAuthError, login
from code_chat_cli.client import get_gemini_client
from code_chat_cli.commands.commit import handle_commit_generation
from code_chat_cli.commands.models import handle_list_models
from code_chat_cli.commands.review import handle_code_review
from code_chat_cli.file_writer import (
    handle_write_mode_confirmation,
)
from code_chat_cli.history import (
    HAVE_READLINE,
    save_chat_history,
    save_history_if_needed,
    save_readline_history,
    setup_readline_history,
)
from code_chat_cli.logger import get_logger, setup_logging, suppress_info_logs
from code_chat_cli.mcp import (
    handle_mcp_run,
    handle_mcp_status,
    handle_mcp_test,
)
from code_chat_cli.prompts import (
    WRITE_MODE_SYSTEM_INSTRUCTION,
)
from code_chat_cli.rag import (
    handle_rag,
    handle_rag_create,
    handle_rag_rm,
    handle_rag_status,
    handle_rag_update,
)

logger = get_logger(__name__)


def run_single_turn_mode(
    chat: Any,
    cli_args: Any,
    chat_history: list[str],
    rag_service: Any | None = None,
) -> None:
    """コンテキスト指定時やワンショットプロンプト実行時の単発処理を行います.

    Args:
        chat (Any): Gemini Chat インスタンス.
        cli_args (Any): コマンドライン引数の名前空間オブジェクト.
        chat_history (list[str]): 対話履歴を格納するリスト.
        rag_service (Any): RAGサービス.

    """
    # mcp オプションが指定されている場合
    is_mcp_mode = cli_args.mcp
    if is_mcp_mode:
        _handle_mcp_single_turn(cli_args, chat_history, rag_service)
        return

    if cli_args.context:
        _handle_context_mode(chat, cli_args, chat_history, rag_service)
    elif cli_args.prompt:
        _handle_prompt_mode(chat, cli_args, chat_history, rag_service)


def run_interactive_loop(
    chat: Any,
    cli_args: Any,
    chat_history: list[str],
    rag_service: Any | None = None,
) -> None:
    """対話型チャットループを実行します.

    Args:
        chat (Any): Gemini Chat インスタンス.
        cli_args (Any): コマンドライン引数の名前空間オブジェクト.
        chat_history (list[str]): 対話履歴を格納するリスト.
        rag_service (Any | None, optional): RAGサービス. Defaults to None.

    """
    setup_readline_history()
    if HAVE_READLINE:
        atexit.register(save_readline_history)

    print("=== Gemini Chat Mode (終了: 'exit' / 保存: '/save <path>') ===\n")

    while True:
        try:
            user_input = input("You > ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            logger.info("会話を終了します.")
            sys.exit(0)

        if not user_input:
            continue

        if user_input.lower() in ["exit", "quit", "q"]:
            logger.info("会話を終了します.")
            break

        # スラッシュコマンド処理 (/save など)
        if _handle_slash_command(user_input, chat_history):
            continue

        # mcp オプション指定時または /mcp コマンド入力時の分岐
        is_mcp_mode = cli_args.mcp or user_input.startswith("/mcp")
        if is_mcp_mode:
            _handle_mcp_interactive(user_input, cli_args, chat_history, rag_service)
            continue

        # 送信テキスト (プロンプト) の構築
        send_text = _build_send_text(user_input, cli_args, rag_service)

        # 履歴追加とストリーミング送信
        chat_history.append(f"### User\n\n{user_input}")
        response_text = _stream_chat_response(chat, send_text)
        chat_history.append(f"### Gemini\n\n{response_text}")

        # -w / --write モード時の処理
        if cli_args.write_mode:
            _handle_write_mode(cli_args, response_text)


def _handle_slash_command(
    user_input: str,
    chat_history: list[str],
) -> bool:
    """コマンド (/save など) を処理します.

    Args:
        user_input (str): ユーザーからの入力文字列.
        chat_history (list[str]): 対話履歴を格納するリスト.

    Returns:
        bool: コマンドとして処理された場合は True, それ以外は False.

    """
    if not user_input.startswith("/save"):
        return False

    parts = user_input.split(maxsplit=1)

    if len(parts) > 1:
        save_chat_history(parts[1], chat_history)
    else:
        logger.error("保存先のファイルパスを指定してください（例: /save result.md）")
    return True


def _build_send_text(
    user_input: str,
    cli_args: Any,
    rag_service: Any | None,
) -> str:
    """ユーザー入力にファイルや RAG, Writeモード指示を統合した送信テキストを構築します.

    Args:
        user_input (str): ユーザーからの入力文字列.
        cli_args (Any): コマンドライン引数の名前空間オブジェクト.
        rag_service (Any | None): RAGサービス.

    Returns:
        str: 構築された送信テキスト.

    """
    send_text = user_input
    files = cli_args.files

    if files:
        files_context = _load_files_context(files)
        if files_context:
            send_text = f"{send_text}\n\n" + "\n\n".join(files_context)
    elif rag_service:
        send_text = _append_rag_context(send_text, user_input, rag_service)

    if cli_args.write_mode:
        send_text += "\n\n(※指示に従って修正した「完全なコード全体」を省略せずに1つのコードブロックで出力してください)"

    return send_text


def _load_files_context(files: list[str]) -> list[str]:
    """指定されたファイル群の内容を取得してコンテキスト文字列のリストを作成します.

    Args:
        files (list[str]): 読み込み対象のファイルパスリスト.

    Returns:
        list[str]: 読み込まれたファイル内容のコンテキスト文字列リスト.

    """
    files_context = []
    for file_path in files:
        try:
            content = Path(file_path).read_text(encoding="utf-8")
            files_context.append(f"--- File: {file_path} ---\n{content}")
        except Exception as e:  # noqa: BLE001 # pylint: disable=broad-exception-caught
            logger.warning("ファイル %s の読み込みに失敗しました: %s", file_path, e)
    return files_context


def _append_rag_context(
    send_text: str,
    user_input: str,
    rag_service: Any,
) -> str:
    """RAG から取得した検索コンテキストをプロンプトに付加します.

    Args:
        send_text (str): 元の送信テキスト.
        user_input (str): ユーザーからの入力文字列.
        rag_service (Any): RAGサービス.

    Returns:
        str: RAGコンテキストが付加された送信テキスト.

    """
    logger.info("RAG コンテキストを検索中: %s", user_input)
    rag_context = _retrieve_rag_context(rag_service, user_input)

    if rag_context:
        return f"{send_text}\n\n--- [関連する参照コード (RAG)] ---\n{rag_context}"

    logger.warning("RAG 検索結果が空でした")
    logger.debug("results: %s", rag_service.vector_store.search_debug(user_input))
    return send_text


def _stream_chat_response(chat: Any, send_text: str) -> str:
    """Gemini にメッセージを送信し, 標準出力にストリーミング表示しながらレスポンス文字列を取得します.

    Args:
        chat (Any): Gemini Chat インスタンス.
        send_text (str): 送信するテキスト.

    Returns:
        str: 受信したレスポンス文字列全体.

    """
    print("Gemini > ", end="", flush=True)
    chunks = []
    for chunk in send_message_stream_with_retry(chat, send_text):
        if chunk.text:
            print(chunk.text, end="", flush=True)
            chunks.append(chunk.text)
    print("\n")

    response_text = "".join(chunks)
    logger.debug("対話レスポンス受信完了 - 文字数: %d", len(response_text))
    return response_text


def _handle_write_mode(cli_args: Any, response_text: str) -> None:
    """書き込みモードの実行確認と適用を行います.

    Args:
        cli_args (Any): コマンドライン引数の名前空間オブジェクト.
        response_text (str): Gemini から返却されたレスポンス本文全体.

    """
    target_files = cli_args.files
    handle_write_mode_confirmation(target_files, response_text)


def _retrieve_rag_context(rag_service: Any, query: str) -> str:
    """RAGサービスからクエリに関連するコードスニペットを取得します.

    Args:
        rag_service (Any): RAG サービスインスタンス.
        query (str): 検索クエリ.

    Returns:
        str: 取得された参照コンテキスト文字列.

    """
    try:
        return rag_service.get_context(query)
    except Exception as e:  # noqa: BLE001 # pylint: disable=broad-exception-caught
        logger.warning("RAGコンテキスト取得時にエラーが発生しました: %s", e)
    return ""


def _build_context_prompt(cli_args: Any, rag_service: Any | None = None) -> str:
    """コンテキスト指定時のプロンプト文字列を構築します.

    Args:
        cli_args (Any): コマンドライン引数の名前空間オブジェクト.
        rag_service (Any | None): RAGサービス.

    Returns:
        str: 構築されたプロンプト文字列.

    """
    prompt_text = cli_args.prompt or ""
    if cli_args.write_mode and prompt_text:
        prompt_text += "\n\n※指示に従って修正した「完全なコード全体」を省略せずに1つのコードブロックで出力してください."

    parts = [
        "以下のソースコード・テキストを読み込んで, 今後の指示に対応してください.\n",
        cli_args.context,
    ]

    if rag_service and prompt_text:
        rag_context = _retrieve_rag_context(rag_service, prompt_text)
        if rag_context:
            parts.append(f"\n--- [関連する参照コード (RAG)] ---\n{rag_context}")

    if prompt_text:
        parts.append(f"\n--- [指示] ---\n{prompt_text}")
    else:
        parts.append(
            "\n準備ができたら「データを読み込みました. どのような対応を行いますか？」と簡潔に返答してください."
        )
    return "\n".join(parts)


def _fetch_response_text(chat: Any, prompt: str, is_write_mode: bool) -> str:
    """メッセージを送信し, 応答テキストを取得・出力します.

    Args:
        chat (Any): Gemini Chat インスタンス.
        prompt (str): 送信するプロンプト文字列.
        is_write_mode (bool): 上書きモードが有効かどうか.

    Returns:
        str: モデルから受信した応答テキスト.

    """
    if is_write_mode:
        response = send_message_with_retry(chat, prompt)
        response_text = response.text or ""
        print(response_text)
        return response_text

    print("Gemini > ", end="", flush=True)
    chunks = []
    for chunk in send_message_stream_with_retry(chat, prompt):
        if chunk.text:
            print(chunk.text, end="", flush=True)
            chunks.append(chunk.text)
    print("\n")
    return "".join(chunks)


def _handle_context_mode(
    chat: Any,
    cli_args: Any,
    chat_history: list[str],
    rag_service: Any | None = None,
) -> None:
    """コンテキストが存在する場合の処理を実行します.

    Args:
        chat (Any): Gemini Chat インスタンス.
        cli_args (Any): コマンドライン引数の名前空間オブジェクト.
        chat_history (list[str]): 対話履歴を格納するリスト.
        rag_service (Any): RAGサービス.

    """
    full_init_prompt = _build_context_prompt(cli_args, rag_service=rag_service)
    file_label = ", ".join(cli_args.files) or "コンテキストテキスト"

    prompt_summary = f"\n\n[指示]: {cli_args.prompt}" if cli_args.prompt else ""
    history_entry = (
        f"### User (Initial Context)\n\n"
        f"[ファイル読み込み: {file_label} ({len(cli_args.context or '')} bytes)]"
        f"{prompt_summary}"
    )
    chat_history.append(history_entry)

    logger.info("ファイル '%s' を Gemini のコンテキストとして送信中...", file_label)

    response_text = _fetch_response_text(chat, full_init_prompt, cli_args.write_mode)
    chat_history.append(f"### Gemini\n\n{response_text}")

    if cli_args.write_mode and cli_args.prompt:
        target_files = cli_args.files
        handle_write_mode_confirmation(target_files, response_text)


def _handle_prompt_mode(
    chat: Any,
    cli_args: Any,
    chat_history: list[str],
    rag_service: Any | None = None,
) -> None:
    """プロンプトのみの場合の処理を実行します.

    Args:
        chat (Any): Gemini Chat インスタンス.
        cli_args (Any): コマンドライン引数の名前空間オブジェクト.
        chat_history (list[str]): 対話履歴を格納するリスト.
        rag_service (Any): RAGサービス.

    """
    prompt_text = cli_args.prompt
    send_text = prompt_text

    if rag_service:
        logger.info("RAG コンテキストを検索中: %s", prompt_text)
        rag_context = _retrieve_rag_context(rag_service, prompt_text)
        if rag_context:
            send_text = (
                f"{send_text}\n\n--- [関連する参照コード (RAG)] ---\n{rag_context}"
            )

    if cli_args.write_mode:
        send_text += "\n\n※指示に従って修正した「完全なコード全体」を省略せずに1つのコードブロックで出力してください."

    print(f"You > {prompt_text}")
    chat_history.append(f"### User\n\n{prompt_text}")

    response_text = _fetch_response_text(
        chat, send_text, is_write_mode=cli_args.write_mode
    )
    logger.debug("レスポンス受信完了 - 文字数: %d", len(response_text))
    chat_history.append(f"### Gemini\n\n{response_text}")

    if cli_args.write_mode:
        target_files = cli_args.files
        handle_write_mode_confirmation(target_files, response_text)


def _setup_cli_logging(cli_args: Any) -> None:
    """CLI 引数に基づいてロギングを設定します.

    Args:
        cli_args (Any): コマンドライン引数の名前空間オブジェクト.

    """
    if not cli_args.debug_mode and (
        cli_args.list_models or cli_args.generate_commit_msg
    ):
        suppress_info_logs()
        return

    log_level = "DEBUG" if cli_args.debug_mode else cli_args.log_level
    setup_logging(level_name=log_level, trace=cli_args.trace_mode)


def _require_rag_api_key() -> None:
    """RAG に必要な API キーが設定されていることを確認します.

    RAG は Embedding API を langchain-google-genai 経由で呼び出すため, --oauth 指定時も
    環境変数の API キーを使用します.

    Raises:
        SystemExit: API キーが未設定の場合, 終了コード 1 で終了します.

    """
    if os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"):
        return

    logger.error(
        "RAG には API キーが必要です. GEMINI_API_KEY を設定してください "
        "(--oauth 指定時も, RAG は API キーを使用します)."
    )
    sys.exit(1)


def _handle_login() -> None:
    """OAuth ログインを実行し, 終了する.

    Raises:
        SystemExit: ログイン成功時は終了コード 0, 失敗時は終了コード 1.

    """
    try:
        login()
    except OAuthError as e:
        logger.error("OAuth ログインを実行できませんでした.")
        print(str(e), file=sys.stderr)
        sys.exit(1)

    logger.info("OAuth で実行するには, --oauth オプションを指定してください")
    sys.exit(0)


def _handle_dry_run(cli_args: Any, config: types.GenerateContentConfig) -> None:
    """ドライランモード指定時の情報出力と終了処理を実行します.

    API 送信を行わずに解析結果を表示します.

    Args:
        cli_args (Any): コマンドライン引数の名前空間オブジェクト.
        config (types.GenerateContentConfig): 生成設定オブジェクト.

    """
    print("[DRY-RUN] Gemini API へのリクエスト送信をスキップします")
    print(f"  サブコマンド: {cli_args.subcommand or 'None'}")
    print(f"  モデル: {cli_args.model or 'None'}")
    print(f"  プロバイダ: {cli_args.provider or 'None'}")
    print(f"  キャッシュ設定: {cli_args.cache}")
    if cli_args.files:
        print("  対象パス:")
        for file_path in cli_args.files:
            print(f"    - {file_path}")
    else:
        print("  対象パス: None")
    if cli_args.input_dirs:
        print("  RAG (index) 入力ディレクトリ:")
        for dir_path in cli_args.input_dirs:
            print(f"    - {dir_path}")
    else:
        print("  RAG 入力ディレクトリ: None")
    print(f"  RAG 出力ディレクトリ: {cli_args.output_dir or 'None'}")
    print(f"  プロンプト: {cli_args.prompt or 'None'}")
    print(f"  コンテキスト長: {len(cli_args.context or '')} 文字")

    print("\n--- [Chat Config (生成設定)] ---")
    print(f"  System Instruction: {config.system_instruction}")
    print(f"  Temperature: {config.temperature}")
    print(
        f"  Auto Function Calling Disable: "
        f"{getattr(config.automatic_function_calling, 'disable', None)}"
    )

    if cli_args.context:
        print("\n--- [収集されたコンテキストプレビュー] ---")
        preview = cli_args.context[:300] + (
            "..." if len(cli_args.context) > 300 else ""
        )
        print(preview)
        print("---------------------------------------")


def _handle_subcommands(client: Any, cli_args: Any) -> None:
    """特定サブコマンドフラグ指定時の独立処理を実行します.

    Args:
        client (Any): Gemini Client インスタンス.
        cli_args (Any): コマンドライン引数の名前空間オブジェクト.

    """
    subcommand = cli_args.subcommand
    if subcommand is None:
        logger.info("chat サブコマンドを実行します")
        list_models = cli_args.list_models
        if list_models:
            try:
                handle_list_models(client)
                sys.exit(0)
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception(
                    "Chat (list_models) コマンドの実行中にエラーが発生しました"
                )
                sys.exit(1)

        generate_commit_msg = cli_args.generate_commit_msg
        if generate_commit_msg:
            try:
                handle_commit_generation(client, cli_args.model)
                sys.exit(0)
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception(
                    "Chat (generate_commit_msg) コマンドの実行中にエラーが発生しました"
                )
                sys.exit(1)

    elif subcommand == "rag":
        logger.info("rag サブコマンドを実行します")
        _handle_rag_subcommand(cli_args)

    elif subcommand == "mcp":
        logger.info("mcp サブコマンドを実行します")
        _handle_mcp_subcommand(cli_args)

    elif subcommand == "cache":
        logger.info("cache サブコマンドを実行します")

    review = cli_args.review
    if review:
        try:
            handle_code_review(
                client,
                cli_args.model,
                staged=cli_args.staged,
                file_path=cli_args.files,
            )
            sys.exit(0)
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("review コマンドの実行中にエラーが発生しました")
            sys.exit(1)


def _handle_rag_subcommand(cli_args: Any) -> None:
    """RAGサブコマンド（create / update / rm / status / prompt）の振る舞いを分岐・実行します.

    Args:
        cli_args (Any): コマンドライン引数の名前空間オブジェクト.

    """
    logger.info("rag サブコマンドを実行します")
    input_dirs = cli_args.input_dirs or ["."]
    output_dir = cli_args.output_dir or "./.chroma_db"
    action = cli_args.subcommand_action

    try:
        if action == "create":
            handle_rag_create(input_dirs, output_dir)
            sys.exit(0)

        if action == "update":
            handle_rag_update(input_dirs, output_dir)
            sys.exit(0)

        if action == "rm":
            handle_rag_rm(output_dir)
            sys.exit(0)

        if action == "status":
            handle_rag_status(input_dirs, output_dir)
            sys.exit(0)

        # アクション未指定かつプロンプトが渡された場合（ワンショット検索）
        prompt = cli_args.prompt
        if prompt:
            prompt_str = " ".join(prompt) if isinstance(prompt, list) else str(prompt)
            logger.info("RAG 検索クエリを実行します: %s", prompt_str)
            handle_rag(prompt_str)
            sys.exit(0)

    except Exception:  # pylint: disable=broad-exception-caught
        action_name = action or "prompt"
        logger.exception("RAG (%s) コマンドの実行中にエラーが発生しました", action_name)
        sys.exit(1)


def _handle_mcp_subcommand(cli_args: Any) -> None:
    """MCPサブコマンド (run / status / test) の振る舞いを分岐・実行します.

    Args:
        cli_args (Any): コマンドライン引数の名前空間オブジェクト.

    """
    logger.info("mcp サブコマンドを実行します")
    action = cli_args.subcommand_action
    config_path = getattr(cli_args, "config_path", None)

    try:
        #        if action == "run":
        #            # prompt 引数 (または query 引数) を取得
        #            user_prompt = getattr(cli_args, "prompt", None) or getattr(
        #                cli_args, "query", None
        #            )
        #            if not user_prompt:
        #                logger.error(
        #                    "実行するプロンプトを指定してください (例: code-chat mcp run 'git status を確認して')"
        #                )
        #                sys.exit(1)
        #
        #            # 非同期関数 handle_mcp_run を同期的に実行して結果を出力
        #            result_text = asyncio.run(
        #                handle_mcp_run(user_prompt=user_prompt, config_path=config_path)
        #            )
        #            print(result_text)
        #            sys.exit(0)

        if action == "status":
            handle_mcp_status(config_path=config_path)
            sys.exit(0)

        if action == "test":
            handle_mcp_test(config_path=config_path)
            sys.exit(0)

        logger.error("不明なサブコマンドアクションです: %s", action)
        sys.exit(1)

    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("MCP (%s) コマンドの実行中にエラーが発生しました", action)
        sys.exit(1)


def _build_chat_config(is_write_mode: bool) -> types.GenerateContentConfig:
    """Write Mode に応じた GenerateContentConfig を作成します.

    Args:
        is_write_mode (bool): 上書きモードが有効かどうか.

    Returns:
        types.GenerateContentConfig: 設定された生成設定オブジェクト.

    """
    if is_write_mode:
        return types.GenerateContentConfig(
            system_instruction=WRITE_MODE_SYSTEM_INSTRUCTION,
            temperature=0.1,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
        )

    system_instruction = (
        "あなたは優秀なプログラミングアシスタントです."
        "提供されたソースコードを把握し, "
        "ユーザーからの指示に従って修正案の提示やコード解説, レビューを行ってください."
    )
    return types.GenerateContentConfig(
        system_instruction=system_instruction,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )


def _handle_mcp_single_turn(
    cli_args: Any,
    chat_history: list[str],
    rag_service: Any | None = None,
) -> None:
    """ワンショットモードで --mcp が指定された場合の MCP 処理を行います.

    --rag との併用時は, RAG で検索したコンテキストをプロンプトに付加して MCP に渡します.

    Args:
        cli_args (Any): コマンドライン引数の名前空間オブジェクト.
        chat_history (list[str]): 対話履歴を格納するリスト.
        rag_service (Any | None, optional): RAGサービス. Defaults to None.

    """
    prompt = cli_args.prompt or cli_args.context
    if not prompt:
        logger.error("MCP 実行用のプロンプトまたはコンテキストを指定してください")
        return

    config_path = getattr(cli_args, "config_path", None)
    chat_history.append(f"### User (MCP)\n\n{prompt}")
    send_prompt = (
        _append_rag_context(prompt, prompt, rag_service) if rag_service else prompt
    )

    print("Gemini (MCP) > ", end="", flush=True)
    try:
        # handle_mcp_run を呼ぶだけでライフサイクル管理からツール実行まで完了する
        result_text = asyncio.run(
            handle_mcp_run(
                user_prompt=send_prompt,
                config_path=config_path,
                use_oauth=cli_args.oauth,
            )
        )
        print(result_text)
        chat_history.append(f"### Gemini (MCP)\n\n{result_text}")
    except Exception as e:  # noqa: BLE001 # pylint: disable=broad-exception-caught
        logger.error("MCP クエリの実行中にエラーが発生しました: %s", e)


def _handle_mcp_interactive(
    user_input: str,
    cli_args: Any,
    chat_history: list[str],
    rag_service: Any | None = None,
) -> None:
    """対話型ループ内から MCP ツール連携クエリ (execute_mcp_query) を実行します.

    --rag との併用時は, RAG で検索したコンテキストをプロンプトに付加して MCP に渡します.

    Args:
        user_input (str): ユーザーからの入力文字列.
        cli_args (Any): コマンドライン引数の名前空間オブジェクト.
        chat_history (list[str]): 対話履歴を格納するリスト.
        rag_service (Any | None, optional): RAGサービス. Defaults to None.

    """
    # `/mcp <prompt>` のようなスラッシュコマンド形式の場合はプレフィックスを除去
    prompt = user_input
    if user_input.startswith("/mcp"):
        prompt = user_input[4:].strip()

    if not prompt:
        logger.error(
            "実行する MCP プロンプトを指定してください (例: /mcp git status を確認して)"
        )
        return

    config_path = getattr(cli_args, "config_path", None)
    chat_history.append(f"### User (MCP)\n\n{prompt}")
    send_prompt = (
        _append_rag_context(prompt, prompt, rag_service) if rag_service else prompt
    )

    print("Gemini (MCP) > ", end="", flush=True)
    try:
        result_text = asyncio.run(
            handle_mcp_run(
                user_prompt=send_prompt,
                config_path=config_path,
                use_oauth=cli_args.oauth,
            )
        )
        print(result_text)
        print()
        chat_history.append(f"### Gemini (MCP)\n\n{result_text}")
    except Exception as e:  # noqa: BLE001 # pylint: disable=broad-exception-caught
        logger.error("MCP クエリの実行中にエラーが発生しました: %s", e)


def main() -> None:
    """Gemini CLI のメイン対話処理を実行します."""
    chat_history: list[str] = []
    auto_save = False

    try:
        cli_args = parse_args()
        _setup_cli_logging(cli_args)
        logger.debug(
            "parsed subcommand: %s, file: %s",
            cli_args.subcommand,
            cli_args.files,
        )

        auto_save = cli_args.auto_save
        input_dirs = cli_args.input_dirs or ["."]
        output_dir = cli_args.output_dir or "./.chroma_db"

        logger.debug("デバッグモードが有効化されました")
        logger.info("Gemini CLI ツールを起動します")

        write_mode = cli_args.write_mode
        config = _build_chat_config(write_mode)

        if cli_args.dry_run:
            _handle_dry_run(cli_args, config)
            sys.exit(0)

        if cli_args.login:
            _handle_login()

        client = get_gemini_client(use_oauth=cli_args.oauth)
        _handle_subcommands(client, cli_args)

        # RAG モードの場合は RagService を初期化
        rag_service = None
        if cli_args.rag:
            _require_rag_api_key()
            rag_service = RagService(input_dirs=input_dirs, output_dir=output_dir)

        chat = client.chats.create(model=cli_args.model, config=config)

        if cli_args.context or cli_args.prompt:
            run_single_turn_mode(chat, cli_args, chat_history, rag_service=rag_service)
        else:
            run_interactive_loop(chat, cli_args, chat_history, rag_service=rag_service)

    except (KeyboardInterrupt, EOFError):
        logger.info("\n[Ctrl+C] 会話を終了します")
        sys.exit(0)
    except (APIError, ServerError, ClientError) as e:
        logger.error("Gemini API エラーにより処理を中断しました: %s", e)
        sys.exit(1)
    except (FileNotFoundError, ValueError, PermissionError):
        logger.exception("ファイル操作でエラーが発生しました")
        sys.exit(1)
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.critical(
            "予期せぬエラーが発生しました: %s",
            e,
            exc_info=logger.isEnabledFor(logging.DEBUG),
        )
        sys.exit(1)
    finally:
        save_history_if_needed(chat_history, auto_save)


if __name__ == "__main__":  # pragma: no cover
    main()
