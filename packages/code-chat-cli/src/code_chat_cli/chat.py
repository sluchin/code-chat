"""Gemini API を使用してローカルコードの参照・対話を行うCLIチャットツール.

このモジュールは, 指定されたファイルやパイプ入力をコンテキストとして読み込み,
Gemini API と対話を行うためのコマンドラインインターフェースを提供します.
ファイルの上書き保存機能や会話ログの自動保存機能を含みます.
"""

import atexit
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path
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
from code_chat_cli.logger import get_logger, setup_logging, suppress_info_logs
from code_chat_cli.prompts import (
    WRITE_MODE_SYSTEM_INSTRUCTION,
)

# pylint: disable=invalid-name
HAVE_READLINE = False
readline: Any = None

try:
    import readline

    HAVE_READLINE = True
except ImportError:
    try:
        import pyreadline3 as readline  # type: ignore[no-redef]

        HAVE_READLINE = True
    except ImportError:
        pass

logger = get_logger(__name__)


def is_partial_code(code: str) -> bool:
    """コードブロック内に省略表現が含まれているか判定します.

    Args:
        code (str): 検証対象のソースコード文字列.

    Returns:
        bool: 省略表現が含まれている場合は True, それ以外は False.
    """
    patterns = [
        # 行全体またはインデント後の行頭が省略コメントになっているパターン
        r"^\s*#\s*\.\.\.\s*$",
        r"^\s*\/\/\s*\.\.\.\s*$",
        # 日本語・英語での典型的な省略指示コメント
        r"#\s*(?:既存の|前の|後の|以降の)?\s*コード",
        r"\/\/\s*(?:既存の|前の|後の|以降の)?\s*コード",
        r"#\s*変更(?:なし|ありません)",
        r"\/\/\s*変更(?:なし|ありません)",
        r"#\s*(?:rest of|remaining)\s*code",
        r"\/\/\s*(?:rest of|remaining)\s*code",
        r"#\s*省略",
        r"\/\/\s*省略",
    ]
    for pattern in patterns:
        if re.search(pattern, code, re.IGNORECASE | re.MULTILINE):
            return True
    return False


def apply_file_modification(target_path: str, new_code: str) -> None:
    """指定された単一ファイルへ修正後コードを書き込みます.

    元のファイルと同じディレクトリに `.bak` 拡張子を付けたバックアップファイルを
    生成した上で, 指定パスのファイルを新しい内容で上書きします.

    Args:
        target_path (str): 上書き対象のファイルパス.
        new_code (str): ファイルに書き込む新しいソースコード文字列.
    """
    path = Path(target_path)
    if not path.is_file():
        logger.error("'%s' は存在しないか, 単一ファイルではありません.", target_path)
        return

    try:
        # バックアップファイルの作成 (.bak)
        bak_path = path.with_suffix(path.suffix + ".bak")
        bak_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        logger.debug("バックアップ作成完了: '%s'", bak_path)

        # 新しいコードの書き込み
        path.write_text(new_code, encoding="utf-8")
        logger.info(
            "'%s' を更新しました. （バックアップ: '%s'）", target_path, bak_path
        )
    except OSError:
        logger.exception("ファイルの書き換えに失敗しました.")


def save_chat_history(file_path: str, history: list[str]) -> None:
    """対話ログを指定されたファイルパスへ保存します.

    指定されたパスの親ディレクトリが存在しない場合は自動的に生成し,
    会話履歴を Markdown 形式で書き込みます.

    Args:
        file_path (str): 保存先のファイルパス.
        history (list[str]): 保存対象の対話履歴リスト.
    """
    try:
        path = Path(file_path)
        # 親ディレクトリが存在しない場合は作成
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n\n".join(history), encoding="utf-8")
        logger.info("対話ログを '%s' に保存しました.", file_path)
    except OSError:
        logger.exception("対話ログファイルの保存に失敗しました.")


def sanitize_code_output(text: str) -> str:
    """LLM の応答テキストからコードブロック記号を除去し, 整形済みコードを返します.

    テキストの先頭および末尾に存在する Markdown のコードブロック囲み記号
    （```python や ``` など）を取り除き, POSIX 標準に適合するよう末尾に
    1 つの改行コード（\n）を保証した文字列を生成します.

    Args:
        text (str): LLM から取得したレスポンス文字列.

    Returns:
        str: サニタイズ処理および末尾改行が付与されたソースコード文字列.
    """
    lines = text.strip().splitlines()

    # 先頭が ``` で始まっていれば除去
    if lines and lines[0].startswith("```"):
        lines.pop(0)
    # 末尾が ``` で終わっていれば除去
    if lines and lines[-1].startswith("```"):
        lines.pop(-1)

    return "\n".join(lines).strip() + "\n"


def handle_write_mode_confirmation(
    target_path_str: str | None, response_text: str
) -> None:
    """Write Mode 時に抽出したコードでファイルを更新します.

    抽出したコードの妥当性を検証し, ユーザーに確認を求めた上でファイルの上書きを行います.

    Args:
        target_path_str (str | None): 書き換え対象のファイルパス.
        response_text (str): Gemini から返却されたレスポンス本文全体.
    """
    logger.debug(
        "handle_write_mode_confirmation 呼び出し - target_path: '%s'", target_path_str
    )

    if not target_path_str:
        logger.error("対象のファイルパスが指定されていません.")
        return

    target_path = Path(target_path_str)
    logger.debug(
        "ファイル存在チェック: path='%s', is_file()=%s",
        target_path.resolve(),
        target_path.is_file(),
    )

    if not target_path.is_file():
        logger.error(
            "'%s' は存在しないか, 通常のファイルではありません.", target_path_str
        )
        return

    code = sanitize_code_output(response_text)
    logger.debug("抽出結果コード長: %d 文字", len(code))

    if not code.strip():
        logger.error(
            "レスポンスから書き込み可能なコードブロックを抽出できませんでした."
        )
        return

    if is_partial_code(code):
        logger.warning(
            "出力コード内に省略（'...' や '変更なし' 等）"
            "が含まれている可能性があります."
            "そのまま上書きするとコードが破損する恐れがあります."
        )

    confirm = (
        input(
            f"\n[Write Mode] 提案されたコード（{len(code.splitlines())} 行）で "
            f"'{target_path_str}' を上書きしますか？ (y/N): "
        )
        .strip()
        .lower()
    )

    logger.debug("ユーザー入力結果: '%s'", confirm)

    if confirm == "y":
        apply_file_modification(target_path_str, code)
    else:
        logger.info("上書きをキャンセルしました.")


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


def run_single_turn_mode(chat: Any, cli_args: Any, chat_history: list[str]) -> None:
    """コンテキスト指定時やワンショットプロンプト実行時の単発処理を行います."""
    if cli_args.context:
        _handle_context_mode(chat, cli_args, chat_history)
    elif cli_args.prompt:
        _handle_prompt_mode(chat, cli_args, chat_history)


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


# 履歴ファイルの保存先指定（例: ホームディレクトリ配下）
HISTORY_FILE = Path.home() / ".code_chat_history"
MAX_HISTORY_LENGTH = 1000


def setup_readline_history() -> None:
    """コマンド履歴の読み込みと自動保存を設定します."""
    if HAVE_READLINE:
        # 履歴ファイルが存在すれば読み込み
        if HISTORY_FILE.exists() and hasattr(readline, "read_history_file"):
            try:
                readline.read_history_file(str(HISTORY_FILE))
            except OSError:
                pass

        # 履歴の最大保持件数を設定
        if hasattr(readline, "set_history_length"):
            readline.set_history_length(MAX_HISTORY_LENGTH)


def save_readline_history() -> None:
    """コマンド履歴をファイルに書き出します."""
    if HAVE_READLINE and hasattr(readline, "write_history_file"):
        try:
            # ディレクトリがない場合は作成して保存
            HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            readline.write_history_file(str(HISTORY_FILE))
        except OSError:
            pass


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
        except KeyboardInterrupt, EOFError:
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


def _setup_cli_logging(cli_args: Any) -> None:
    """CLI 引数に基づいてロギングを設定します."""
    if not cli_args.debug and (cli_args.list_models or cli_args.generate_commit_msg):
        suppress_info_logs()
        return

    log_level = "DEBUG" if cli_args.debug else cli_args.log_level
    setup_logging(level_name=log_level)


def _handle_subcommands(client: Any, cli_args: Any) -> None:
    """特定サブコマンドフラグ指定時の独立処理を実行します."""
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


def _save_history_if_needed(
    chat_history: list[str], output_file: str | None, auto_save: bool
) -> None:
    """必要に応じて対話履歴をファイルに保存します."""
    if not chat_history:
        return

    target_path = output_file
    if auto_save and not target_path:
        timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
        target_path = f"{timestamp}_chat.md"

    if target_path:
        save_chat_history(target_path, chat_history)


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

    except KeyboardInterrupt, EOFError:
        logger.info("\n[Ctrl+C] 会話を終了します.")
        sys.exit(0)
    except (APIError, ServerError, ClientError) as e:
        logger.error("Gemini API エラーにより処理を中断しました: %s", e)
        sys.exit(1)
    except FileNotFoundError, ValueError, PermissionError:
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
        _save_history_if_needed(chat_history, output_file, auto_save)


if __name__ == "__main__":  # pragma: no cover
    main()
