"""Gemini API を使用してローカルコードの参照・対話を行うCLIチャットツール.

このモジュールは, 指定されたファイルやパイプ入力をコンテキストとして読み込み,
Gemini API と対話を行うためのコマンドラインインターフェースを提供します.
ファイルの上書き保存機能や会話ログの自動保存機能を含みます.
"""

import atexit
import logging
import sys
import time  # pylint: disable=unused-import # noqa: F401
from pathlib import Path  # pylint: disable=unused-import # noqa: F401
from typing import Any

from google.genai import types
from google.genai.errors import APIError, ClientError, ServerError

from code_chat_cli.api import (
    send_message_stream_with_retry,
    send_message_with_retry,
)
from code_chat_cli.args import parse_args
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
from code_chat_cli.index import handle_ask, handle_index
from code_chat_cli.logger import get_logger, setup_logging, suppress_info_logs
from code_chat_cli.prompts import (
    WRITE_MODE_SYSTEM_INSTRUCTION,
)

logger = get_logger(__name__)


def run_single_turn_mode(chat: Any, cli_args: Any, chat_history: list[str]) -> None:
    """コンテキスト指定時やワンショットプロンプト実行時の単発処理を行います."""
    if cli_args.context:
        _handle_context_mode(chat, cli_args, chat_history)
    elif cli_args.prompt:
        _handle_prompt_mode(chat, cli_args, chat_history)


def run_interactive_loop(
    chat: Any, cli_args: Any, output_file: str | None, chat_history: list[str]
) -> None:
    """対話型チャットループを実行します.

    ユーザーからの標準入力を受け取り, Gemini と連続して対話を行います.
    終了コマンドや保存コマンドのハンドリングも含みます.

    Args:
        chat (Any): Gemini Chat インスタンス.
        cli_args (Any): コマンドライン引数の名前空間オブジェクト.
        output_file (str | None): 履歴保存先ファイルパス.
        chat_history (list[str]): 対話履歴を格納するリスト.
    """
    # readline 履歴の初期化
    setup_readline_history()
    # プログラム終了時（または Ctrl+C 時）に履歴を保存
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
            # break

        if not user_input:
            continue

        if user_input.lower() in ["exit", "quit", "q"]:
            logger.info("会話を終了します.")
            break

        if user_input.startswith("/save"):
            parts = user_input.split(maxsplit=1)
            save_path = parts[1] if len(parts) > 1 else output_file
            if save_path:
                save_chat_history(save_path, chat_history)
            else:
                logger.error(
                    "保存先のファイルパスを指定してください（例: /save result.md）"
                )
            continue

        send_text = user_input
        if cli_args.write_mode:
            send_text += "\n\n(※指示に従って修正した「完全なコード全体」を省略せずに1つのコードブロックで出力してください)"

        chat_history.append(f"### User\n\n{user_input}")

        print("Gemini > ", end="", flush=True)
        chunks = []
        for chunk in send_message_stream_with_retry(chat, send_text):
            if chunk.text:
                print(chunk.text, end="", flush=True)
                chunks.append(chunk.text)
        print("\n")

        response_text = "".join(chunks)
        logger.debug("対話レスポンス受信完了 - 文字数: %d", len(response_text))
        chat_history.append(f"### Gemini\n\n{response_text}")

        if cli_args.write_mode:
            handle_write_mode_confirmation(cli_args.target_path, response_text)


def _build_context_prompt(cli_args: Any) -> str:
    """コンテキスト指定時のプロンプト文字列を構築します."""
    prompt_text = cli_args.prompt or ""
    if cli_args.write_mode and prompt_text:
        prompt_text += "\n\n※指示に従って修正した「完全なコード全体」を省略せずに1つのコードブロックで出力してください."

    parts = [
        "以下のソースコード・テキストを読み込んで, 今後の指示に対応してください.\n",
        cli_args.context,
    ]
    if prompt_text:
        parts.append(f"\n--- [指示] ---\n{prompt_text}")
    else:
        parts.append(
            "\n準備ができたら「データを読み込みました. どのような対応を行いますか？」と簡潔に返答してください."
        )
    return "\n".join(parts)


def _fetch_response_text(chat: Any, prompt: str, is_write_mode: bool) -> str:
    """メッセージを送信し, 応答テキストを取得・出力します."""
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


def _handle_context_mode(chat: Any, cli_args: Any, chat_history: list[str]) -> None:
    """コンテキストが存在する場合の処理."""
    full_init_prompt = _build_context_prompt(cli_args)
    file_label = getattr(cli_args, "file", None) or "コンテキストテキスト"

    prompt_summary = f"\n\n[指示]: {cli_args.prompt}" if cli_args.prompt else ""
    history_entry = (
        f"### User (Initial Context)\n\n"
        f"[ファイル読み込み: {file_label} ({len(cli_args.context)} bytes)]"
        f"{prompt_summary}"
    )
    chat_history.append(history_entry)

    logger.info("ファイル '%s' を Gemini のコンテキストとして送信中...", file_label)

    response_text = _fetch_response_text(chat, full_init_prompt, cli_args.write_mode)
    chat_history.append(f"### Gemini\n\n{response_text}")

    if cli_args.write_mode and cli_args.prompt:
        handle_write_mode_confirmation(cli_args.target_path, response_text)


def _handle_prompt_mode(chat: Any, cli_args: Any, chat_history: list[str]) -> None:
    """プロンプトのみの場合の処理."""
    prompt_text = cli_args.prompt
    if cli_args.write_mode:
        prompt_text += "\n\n※指示に従って修正した「完全なコード全体」を省略せずに1つのコードブロックで出力してください."

    print(f"You > {prompt_text}")
    chat_history.append(f"### User\n\n{prompt_text}")

    response_text = _fetch_response_text(chat, prompt_text, is_write_mode=False)
    logger.debug("レスポンス受信完了 - 文字数: %d", len(response_text))
    chat_history.append(f"### Gemini\n\n{response_text}")

    if cli_args.write_mode:
        handle_write_mode_confirmation(cli_args.target_path, response_text)


def _setup_cli_logging(cli_args: Any) -> None:
    """CLI 引数に基づいてロギングを設定します."""
    if not cli_args.debug and (cli_args.list_models or cli_args.generate_commit_msg):
        suppress_info_logs()
        return

    log_level = "DEBUG" if cli_args.debug else cli_args.log_level
    setup_logging(level_name=log_level)


def _handle_subcommands(client: Any, cli_args: Any) -> None:
    """特定サブコマンドフラグ指定時の独立処理を実行します."""
    command = getattr(cli_args, "command", None)
    if command == "index":
        try:
            handle_index(cli_args.repo_path)
            sys.exit(0)
        except Exception:  # noqa: BLE001 # pylint: disable=broad-exception-caught
            sys.exit(1)
    elif command == "ask":
        try:
            handle_ask(cli_args.query)
            sys.exit(0)
        except Exception:  # noqa: BLE001 # pylint: disable=broad-exception-caught
            sys.exit(1)

    if getattr(cli_args, "list_models", False):
        try:
            handle_list_models(client)
            sys.exit(0)
        except Exception:  # noqa: BLE001 # pylint: disable=broad-exception-caught
            sys.exit(1)

    if getattr(cli_args, "generate_commit_msg", False):
        try:
            handle_commit_generation(client, cli_args.model)
            sys.exit(0)
        except Exception:  # noqa: BLE001 # pylint: disable=broad-exception-caught
            sys.exit(1)

    if getattr(cli_args, "review", False):
        try:
            handle_code_review(
                client,
                cli_args.model,
                staged=getattr(cli_args, "staged", False),
                file_path=getattr(cli_args, "target_path", None),
            )
            sys.exit(0)
        except Exception:  # noqa: BLE001 # pylint: disable=broad-exception-caught
            sys.exit(1)


def _build_chat_config(is_write_mode: bool) -> types.GenerateContentConfig:
    """Write Mode に応じた GenerateContentConfig を作成します."""
    if is_write_mode:
        return types.GenerateContentConfig(
            system_instruction=WRITE_MODE_SYSTEM_INSTRUCTION,
            temperature=0.1,
        )

    system_instruction = (
        "あなたは優秀なプログラミングアシスタントです."
        "提供されたソースコードを把握し, "
        "ユーザーからの指示に従って修正案の提示やコード解説, レビューを行ってください."
    )
    return types.GenerateContentConfig(
        system_instruction=system_instruction,
    )


def main() -> None:
    """Gemini CLI のメイン対話処理を実行します."""
    chat_history: list[str] = []
    output_file: str | None = None
    auto_save = False

    try:
        cli_args = parse_args()
        # auto_save 属性が存在しないモック引数にも対応できるように getattr を使用
        auto_save = getattr(cli_args, "auto_save", False)
        output_file = getattr(cli_args, "output_path", None)

        _setup_cli_logging(cli_args)
        logger.debug("デバッグモードが有効化されました.")
        logger.info("Gemini CLI ツールを起動します.")

        client = get_gemini_client()
        _handle_subcommands(client, cli_args)

        config = _build_chat_config(cli_args.write_mode)
        chat = client.chats.create(model=cli_args.model, config=config)

        if cli_args.context or cli_args.prompt:
            run_single_turn_mode(chat, cli_args, chat_history)
        else:
            run_interactive_loop(chat, cli_args, output_file, chat_history)

    except (KeyboardInterrupt, EOFError):
        logger.info("\n[Ctrl+C] 会話を終了します.")
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
        save_history_if_needed(chat_history, output_file, auto_save)


if __name__ == "__main__":  # pragma: no cover
    main()
