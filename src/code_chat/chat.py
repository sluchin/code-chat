"""Gemini API を使用してローカルコードの参照・対話を行うCLIチャットツール.

このモジュールは、指定されたファイルやパイプ入力をコンテキストとして読み込み、
Gemini API と対話を行うためのコマンドラインインターフェースを提供します.
ファイルの上書き保存機能や会話ログの自動保存機能を含みます.
"""

import re
import subprocess
import sys
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from google.genai import types
from google.genai.errors import APIError

from code_chat.args import parse_args
from code_chat.client import get_gemini_client
from code_chat.git_utils import get_git_diff
from code_chat.logger import get_logger, setup_logging, suppress_info_logs

logger = get_logger(__name__)

COMMIT_PROMPT_TEMPLATE_JA = """\
以下の git diff の内容を分析し、適切な Git コミットメッセージを作成してください。

【制約事項】
- 1行目は変更内容を簡潔に要約したタイトル（50文字程度）にしてください。
- 必要に応じて空行を挟み、箇条書きで変更理由や詳細を記述してください。
- プレフィックス（feat:, fix:, docs:, refactor:, test: など）を使用してください。
- 記述は日本語で行ってください。
- 余計な解説やコードブロックの枠（``` など）は含めず、コミットメッセージ本文のみを出力してください。

【git diff】
{diff}
"""

COMMIT_PROMPT_TEMPLATE_EN = """\
Analyze the following git diff and generate a concise, professional Git commit message in English.

[Constraints]
- Follow Conventional Commits format (e.g., feat:, fix:, docs:, refactor:, test:, chore:).
- Line 1: Summary title written in the imperative mood (e.g., "add feature" instead of "added feature"), within 50 characters.
- Leave one blank line, followed by bullet points explaining the changes and reasons if necessary.
- Output ONLY the commit message body. Do NOT wrap it in code blocks (```) or include any extra conversational text.

[git diff]
{diff}
"""

WRITE_MODE_SYSTEM_INSTRUCTION = """
あなたはコード自動生成アシスタントです。
指定されたファイルを完全に置き換えるための実行可能なコードのみを出力してください。

【厳格な遵守事項】
1. Markdown のコードブロック記号（```python や ```）を含めないでください。
2. 挨拶、解説、説明文、前置き、後書きは一切含めないでください。
3. 出力の1文字目から最後の文字まで、すべてPythonソースコードとして直接実行可能なテキストのみを出力してください。
"""


def is_partial_code(code: str) -> bool:
    """コードブロック内に省略表現が含まれているか判定します.

    Args:
        code (str): 検証対象のソースコード文字列.

    Returns:
        bool: 省略表現が含まれている場合は True、それ以外は False.
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
    生成した上で、指定パスのファイルを新しい内容で上書きします.

    Args:
        target_path (str): 上書き対象のファイルパス.
        new_code (str): ファイルに書き込む新しいソースコード文字列.
    """
    path = Path(target_path)
    if not path.is_file():
        logger.error("'%s' は存在しないか、単一ファイルではありません.", target_path)
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

    指定されたパスの親ディレクトリが存在しない場合は自動的に生成し、
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
    """LLM の応答テキストからコードブロック記号を除去し、整形済みコードを返します.

    テキストの先頭および末尾に存在する Markdown のコードブロック囲み記号
    （```python や ``` など）を取り除き、POSIX 標準に適合するよう末尾に
    1 つの改行コード（\n）を保証した文字列を生成します。

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
            "'%s' は存在しないか、通常のファイルではありません.", target_path_str
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
            "出力コード内に省略（'...' や '変更なし' 等）が含まれている可能性があります."
            "そのまま上書きするとコードが破損する恐れがあります."
        )

    confirm = (
        input(
            f"\n[Write Mode] 提案されたコード（{len(code.splitlines())} 行）で '{target_path_str}' を上書きしますか？ (y/N): "
        )
        .strip()
        .lower()
    )

    logger.debug("ユーザー入力結果: '%s'", confirm)

    if confirm == "y":
        apply_file_modification(target_path_str, code)
    else:
        logger.info("上書きをキャンセルしました.")


def handle_commit_msg_generation(
    client: Any, model_name: str, lang: str = "en"
) -> None:
    """Git の diff（差分）を取得し、Gemini API を用いてコミットメッセージを自動生成します.

    `git diff --staged`（ステージング済み差分）および `git diff`（未ステージング差分）を
    読み取り、変更内容が存在する場合に指定された言語で Conventional Commits 形式に沿った
    適切なコミットメッセージを生成して標準出力に表示します。

    Args:
        client (Any): Gemini API クライアントインスタンス.
        model_name (str): 使用する Gemini モデル名.
        lang (str, optional): コミットメッセージの出力言語（例: "ja", "en"）. デフォルトは "en".

    Raises:
        subprocess.CalledProcessError: Git コマンドの実行に失敗した場合.
        APIError: Gemini API 呼び出し時に通信エラーや 503 等が発生した場合.
        Exception: その他の予期せぬエラーが発生した場合.
    """
    try:
        diff_text = get_git_diff()

        if not diff_text:
            print(
                "変更（git diff）が検出されませんでした。ファイルを修正するか `git add` してください。"
            )
            return

        # 言語に応じたテンプレートの選択（標準を日本語に設定）
        template = (
            COMMIT_PROMPT_TEMPLATE_JA if lang == "ja" else COMMIT_PROMPT_TEMPLATE_EN
        )
        prompt = template.format(diff=diff_text)

        response_stream = send_message_stream_with_retry(
            chat=client.chats.create(model=model_name), prompt=prompt
        )

        for chunk in response_stream:
            print(chunk.text, end="", flush=True)
        print()

    except subprocess.CalledProcessError:
        logger.exception("Git コマンドの実行に失敗しました")
        raise
    except APIError:
        logger.exception("Gemini API でエラーが発生しました")
        raise
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("予期せぬエラーが発生しました")
        raise


def _is_retryable_error(e: APIError) -> bool:
    """APIError がリトライ対象（503, 429 一時的エラー等）か判定します.

    エラーオブジェクトの `code` 属性およびエラーメッセージ文字列を参照し、
    503 Service Unavailable や 429 Too Many Requests などの一時的な通信エラーであるかを評価します.

    Args:
        e (APIError): 検証対象の Gemini API 例外オブジェクト.

    Returns:
        bool: リトライ対象のエラーである場合は True、400 Bad Request 等のリトライ不可エラーの場合は False.
    """
    code = getattr(e, "code", None)
    if code is not None:
        try:
            if int(code) in (503, 429):
                return True
        except ValueError, TypeError:
            pass

    # code 属性で判定できない場合はメッセージ文字列から判定
    err_msg = str(e)

    return "503" in err_msg or "429" in err_msg


def send_message_stream_with_retry(
    chat: Any,
    prompt: str,
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
) -> Iterator[Any]:
    """Gemini API へのストリーミングリクエストを送信し、通信エラー発生時にリトライを行います.

    イテレーション中の API エラー（503/429等）もキャッチして再試行します。
    途中でエラーが発生した場合は画面に通知し、リトライ時は最初からメッセージを送り直します.

    Args:
        chat (Any): Gemini Chat インスタンス.
        prompt (str): 送信するプロンプト文字列.
        max_retries (int, optional): 最大リトライ回数. Defaults to 3.
        initial_delay (float, optional): 初回リトライ時の待ち時間（秒）. Defaults to 1.0.
        backoff_factor (float, optional): 指数バックオフの倍率. Defaults to 2.0.

    Yields:
        Any: Gemini API からのレスポンスチャンク.

    Raises:
        APIError: 最大リトライ回数を超えてエラーが発生した場合.
    """
    delay = initial_delay

    for attempt in range(1, max_retries + 1):
        yielded_any = False  # チャンクを1つでも上位へ返したかのフラグ

        try:
            response_stream = chat.send_message_stream(prompt)

            # イテレーション（データ受信）自体も try ブロック内で実行
            for chunk in response_stream:
                yielded_any = True
                yield chunk

            # 正常にストリームを最後まで消費できたら終了
            return

        except APIError as e:
            # すでに一部のレスポンスを返している場合は、重複防止のためリトライせずに raise
            if yielded_any:
                logger.error(
                    "ストリーミングの受信途中でエラーが発生しました（一部出力済みのためリトライ中断）: %s",
                    e,
                )
                raise

            # 400 Bad Request などリトライ不可のエラーは即座に raise
            if not _is_retryable_error(e):
                logger.error("リトライ不可な API エラーが発生しました: %s", e)
                raise

            logger.warning(
                "Gemini API 通信エラー (試行 %d/%d): %s", attempt, max_retries, e
            )

            if attempt == max_retries:
                logger.error("最大リトライ回数 (%d 回) に達しました。", max_retries)
                raise

            print(
                f"\n[一時的なエラーが発生しました ({e.code if hasattr(e, 'code') else '503'})。{delay:.1f}秒後に再試行します... ({attempt}/{max_retries})]",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(delay)
            delay *= backoff_factor


def main() -> None:
    """Gemini CLI のメイン対話処理を実行する.

    コマンドライン引数の解析、クライアントの初期化、コンテキスト情報の送出、
    ユーザーとのリアルタイム対話ループ、および終了時の履歴保存やファイル自動書き換え処理を制御します.

    Raises:
        APIError: Gemini API との通信中に発生したエラー.
        FileNotFoundError: コンテキストファイル等が見つからない場合のエラー.
        ValueError: コマンドライン引数等の指定値が不正な場合のエラー.
        PermissionError: ファイルへのアクセス権限が不足している場合のエラー.
    """
    chat_history: list[str] = []
    output_file = None
    client = None

    try:
        # 引数・オプションの解析とプロンプトの組み立て
        cli_args = parse_args()

        # ログレベル制御の判定
        if cli_args.list_models or cli_args.generate_commit_msg:
            # -g オプション指定時は即座に INFO ログを無効化
            suppress_info_logs()
        else:
            # -D / --debug が指定されていれば DEBUG、
            # そうでなければ --log-level の値を採用
            log_level = "DEBUG" if cli_args.debug else cli_args.log_level
            setup_logging(level_name=log_level)

        logger.debug("デバッグモードが有効化されました.")
        logger.info("Gemini CLI ツールを起動します.")

        # クライアント作成
        client = get_gemini_client()

        # --list-models オプションが指定された場合
        if cli_args.list_models:
            try:
                client = get_gemini_client()
                print("利用可能なモデル一覧:")
                for model in client.models.list():
                    # generateContent をサポートしているモデルを表示
                    if "generateContent" in model.supported_actions:
                        model_id = model.name.replace("models/", "")
                        print(f"- {model_id} ({model.display_name})")
                sys.exit(0)
            except Exception:  # pylint: disable=broad-exception-caught
                logger.exception("モデル一覧の取得に失敗しました")
                sys.exit(1)

        if cli_args.generate_commit_msg:
            try:
                handle_commit_msg_generation(client, cli_args.model)
            except Exception:  # noqa: BLE001 # pylint: disable=broad-exception-caught
                sys.exit(1)
            sys.exit(0)

        # 保存ファイル
        output_file = cli_args.output_path

        # システム指示（書き換えモードの有無で動作を変更）
        system_instruction = (
            "あなたは優秀なプログラミングアシスタントです。"
            "提供されたソースコードを把握し、"
            "ユーザーからの指示に従って修正案の提示やコード解説、レビューを行ってください。"
        )

        if cli_args.write_mode:
            config = types.GenerateContentConfig(
                system_instruction=WRITE_MODE_SYSTEM_INSTRUCTION,
                temperature=0.1,
            )
        else:
            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
            )
        # 動的に選択されたモデルを使用
        chat = client.chats.create(model=cli_args.model, config=config)

        if cli_args.context:
            # コンテキスト（ファイルやパイプ入力）が存在する場合
            initial_prompt_parts = [
                "以下のソースコード・テキストを読み込んで、今後の指示に対応してください。\n",
                cli_args.context,
            ]
            if cli_args.prompt:
                prompt_text = cli_args.prompt
                if cli_args.write_mode:
                    prompt_text += "\n\n※指示に従って修正した「完全なコード全体」を省略せずに1つのコードブロックで出力してください。"
                initial_prompt_parts.append(f"\n--- [指示] ---\n{prompt_text}")
            else:
                initial_prompt_parts.append(
                    "\n準備ができたら「データを読み込みました。どのような対応を行いますか？」と簡潔に返答してください。"
                )

            full_init_prompt = "\n".join(initial_prompt_parts)
            chat_history.append(f"### User (Initial Context)\n\n{full_init_prompt}")

            logger.info("Gemini にコンテキストを送信中...")
            response = chat.send_message(full_init_prompt)
            print(f"\nGemini > {response.text}\n")
            chat_history.append(f"### Gemini\n\n{response.text}")

            # -w モードかつ初期プロンプト指示があった場合の上書き確認
            if cli_args.write_mode and cli_args.prompt:
                handle_write_mode_confirmation(cli_args.target_path, response.text)

        elif cli_args.prompt:
            prompt_text = cli_args.prompt
            if cli_args.write_mode:
                prompt_text += "\n\n※指示に従って修正した「完全なコード全体」を省略せずに1つのコードブロックで出力してください。"

            print(f"You > {prompt_text}")
            chat_history.append(f"### User\n\n{prompt_text}")

            print("Gemini > ", end="", flush=True)
            chunks = []
            # リトライ制御を内包したジェネレータから安全に受領
            for chunk in send_message_stream_with_retry(chat, prompt_text):
                if chunk.text:
                    print(chunk.text, end="", flush=True)
                    chunks.append(chunk.text)
            print("\n")

            response_text = "".join(chunks)
            logger.debug("レスポンス受信完了 - 文字数: %d", len(response_text))
            chat_history.append(f"### Gemini\n\n{response_text}")

            if cli_args.write_mode:
                handle_write_mode_confirmation(cli_args.target_path, response_text)
        else:
            # 通常のチャットモード
            print("=== Gemini Chat Mode (終了: 'exit' / 保存: '/save <path>') ===\n")

        # 対話ループ
        while True:
            user_input = input("You > ").strip()

            if not user_input:
                continue

            # 終了判定
            if user_input.lower() in ["exit", "quit", "q"]:
                logger.info("会話を終了します.")
                break

            # 途中での保存コマンド (`/save filename.md`)
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
            # リトライ制御を内包したジェネレータから安全に受領
            for chunk in send_message_stream_with_retry(chat, send_text):
                if chunk.text:
                    print(chunk.text, end="", flush=True)
                    chunks.append(chunk.text)
            print("\n")

            response_text = "".join(chunks)
            logger.debug("対話レスポンス受信完了 - 文字数: %d", len(response_text))
            chat_history.append(f"### Gemini\n\n{response_text}")

            # 書き換えモード（-w）の処理: ユーザーに適用を確認して書き込む
            if cli_args.write_mode:
                handle_write_mode_confirmation(cli_args.target_path, response_text)

    # 例外処理・終了時の保存処理
    except KeyboardInterrupt, EOFError:
        logger.info("\n[Ctrl+C] 会話を終了します。")
    except APIError:
        logger.exception("Gemini APIでエラーが発生しました")
        sys.exit(1)
    except FileNotFoundError, ValueError, PermissionError:
        logger.exception("ファイル操作でエラーが発生しました")
        sys.exit(1)
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.critical("予期せぬエラーが発生しました: %s", e, exc_info=True)
        sys.exit(1)
    finally:
        if chat_history:
            # -s フラグ指定時はタイムスタンプからファイル名生成
            if cli_args.auto_save and not output_file:
                timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
                output_file = f"{timestamp}_chat.md"

            if output_file:
                save_chat_history(output_file, chat_history)


if __name__ == "__main__":  # pragma: no cover
    main()
