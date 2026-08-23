"""Gemini API を使用してローカルコードの参照・対話を行うCLIチャットツール.

このモジュールは, 指定されたファイルやパイプ入力をコンテキストとして読み込み,
Gemini API と対話を行うためのコマンドラインインターフェースを提供します.
ファイルの上書き保存機能や会話ログの自動保存機能を含みます.
"""

import atexit
import logging
import os
import re
import subprocess
import sys
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from google.genai import types
from google.genai.errors import APIError, ClientError, ServerError

from code_chat_cli.args import parse_args
from code_chat_cli.client import get_gemini_client
from code_chat_cli.constants import TEXT_EXTENSIONS
from code_chat_cli.git_utils import get_git_diff
from code_chat_cli.logger import get_logger, setup_logging, suppress_info_logs

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

COMMIT_PROMPT_TEMPLATE_JA = """\
以下の git diff の内容を分析し, 適切な Git コミットメッセージを作成してください.

【制約事項】
- 1行目は変更内容を簡潔に要約したタイトル（50文字程度）にしてください.
- 必要に応じて空行を挟み, 箇条書きで変更理由や詳細を記述してください.
- プレフィックス（feat:, fix:, docs:, refactor:, test: など）を使用してください.
- 記述は日本語で行ってください.
- 余計な解説やコードブロックの枠（``` など）は含めず, コミットメッセージ本文のみを出力してください.

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
あなたはコード自動生成アシスタントです.
指定されたファイルを完全に置き換えるための実行可能なコードのみを出力してください.

【厳格な遵守事項】
1. Markdown のコードブロック記号（```python や ```）を含めないでください.
2. 挨拶, 解説, 説明文, 前置き, 後書きは一切含めないでください.
3. 出力の1文字目から最後の文字まで, すべてPythonソースコードとして直接実行可能なテキストのみを出力してください.
"""

REVIEW_PROMPT_TEMPLATE = """\
あなたはプロのソフトウェアエンジニアです. 以下のコード差分（diff）またはファイル内容を詳細にレビューしてください.

### レビュー観点
1. **潜在的なバグ・不具合**: ヌルポインタ, エッジケースの考慮漏れ, リソースリークなど
2. **パフォーマンス・効率性**: 不要なループや不必要な処理
3. **コード品質・可読性**: 命名規則, 複雑度の高い処理の簡略化
4. **セキュリティ**: 脆弱性や安全でない実装

### レビュー対象
{code}
"""


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


def handle_commit_msg_generation(
    client: Any, model_name: str, lang: str = "en"
) -> None:
    """Git の diff（差分）を取得し, Gemini API を用いてコミットメッセージを自動生成します.

    `git diff --staged`（ステージング済み差分）および `git diff`（未ステージング差分）を
    読み取り, 変更内容が存在する場合に指定された言語で Conventional Commits 形式に沿った
    適切なコミットメッセージを生成して標準出力に表示します.

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
                "変更（git diff）が検出されませんでした.ファイルを修正するか `git add` してください."
            )
            return

        # 言語に応じたテンプレートの選択（標準を日本語に設定）
        template = (
            COMMIT_PROMPT_TEMPLATE_JA if lang == "ja" else COMMIT_PROMPT_TEMPLATE_EN
        )
        prompt = template.format(diff=diff_text)

        try:
            response_stream = send_message_stream_with_retry(
                chat=client.chats.create(model=model_name), prompt=prompt
            )

            for chunk in response_stream:
                print(chunk.text, end="", flush=True)
            print()

        except Exception as e:  # pylint: disable=broad-exception-caught
            error_detail = (
                str(e) if logger.isEnabledFor(logging.DEBUG) else type(e).__name__
            )
            logger.error(
                "コミットメッセージの生成中にエラーが発生しました: %s",
                error_detail,
            )
            raise

    except subprocess.CalledProcessError as e:
        logger.error("Git コマンドの実行に失敗しました: %s", e)
        raise
    except (APIError, ServerError, ClientError) as e:
        error_detail = (
            str(e) if logger.isEnabledFor(logging.DEBUG) else type(e).__name__
        )
        logger.error("Gemini API でエラーが発生しました: %s", error_detail)
        raise
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("予期せぬエラーが発生しました: %s", e)
        raise


def _collect_directory_files(target_dir: Path) -> str:
    """指定ディレクトリ配下のテキストファイルを走査・収集します.

    指定されたディレクトリ配下を再帰的に検索し、指定の拡張子を持つ
    テキストファイルの内容を単一の文字列に結合して返します.
    特定の大規模・生成ディレクトリ（.git, node_modules等）は除外されます.

    Args:
        target_dir (Path): 走査対象のディレクトリパス.

    Returns:
        str: 収集されたファイル群の内容を結合したテキスト.
    """
    ignored_dirs = {".git", "__pycache__", ".venv", ".chroma_db", "node_modules"}
    collected_files: list[str] = []

    for root, dirs, files in os.walk(target_dir):
        dirs[:] = [d for d in dirs if d not in ignored_dirs]
        for file in files:
            file_p = Path(root) / file
            if file_p.suffix.lower() not in TEXT_EXTENSIONS:
                continue
            try:
                content = file_p.read_text(encoding="utf-8")
                collected_files.append(f"=== File: {file_p} ===\n{content}")
            except (OSError, UnicodeDecodeError) as e:
                print(
                    f"スキップ (読み込み失敗): {file_p} - {e}",
                    file=sys.stderr,
                )

    return "\n\n".join(collected_files)


def _get_git_diff(staged: bool) -> str | None:
    """git diff から変更差分を取得します.

    Args:
        staged (bool): True の場合 `--cached` (ステージング済み) 差分を取得する.

    Returns:
        str | None: 取得した差分文字列. 実行失敗時または git コマンドが
            存在しない場合は None を返す.
    """
    cmd = ["git", "diff", "--cached"] if staged else ["git", "diff"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            print(
                f"エラー: git diff の実行に失敗しました:\n{result.stderr}",
                file=sys.stderr,
            )
            return None
        return result.stdout.strip()
    except FileNotFoundError:
        print("エラー: git コマンドが見つかりません.", file=sys.stderr)
        return None


def handle_code_review(
    client: Any,
    model_name: str,
    staged: bool = False,
    file_path: str | None = None,
) -> None:
    """コード差分または指定ファイルを解析し, LLM によるコードレビュー結果を表示する.

    Args:
        client (Any): Gemini API クライアントインスタンス.
        model_name (str): 使用する Gemini モデル名.
        staged (bool, optional): True の場合, git diff の --cached
            (ステージング済み) 差分を対象にする. Defaults to False.
        file_path (str | None, optional): レビュー対象のファイルまたは
            ディレクトリのパス. 指定された場合は git diff ではなく
            ファイル内容全体をレビューする. Defaults to None.
    """
    target_code: str | None = ""

    if file_path:
        path = Path(file_path)
        if not path.exists():
            print(f"エラー: 指定されたパスが存在しません: {file_path}", file=sys.stderr)
            return

        if path.is_dir():
            target_code = _collect_directory_files(path)
        else:
            try:
                content = path.read_text(encoding="utf-8")
                target_code = f"=== File: {path} ===\n{content}"
            except (OSError, UnicodeDecodeError) as e:
                print(f"エラー: ファイルの読み込みに失敗しました: {e}", file=sys.stderr)
                return
    else:
        target_code = _get_git_diff(staged)

    if not target_code:
        print("レビュー対象のコードまたは変更点が見つかりませんでした.")
        return

    prompt = REVIEW_PROMPT_TEMPLATE.format(code=target_code)

    print("コードレビューを実行中...\n")
    response = client.models.generate_content_stream(
        model=model_name,
        contents=prompt,
    )
    for chunk in response:
        print(chunk.text, end="", flush=True)
    print()


def _extract_retry_delay(e: Exception) -> float | None:
    """APIのエラー詳細情報 (RetryInfo) から推奨待機時間 (秒) を抽出します.

    Args:
        e (Exception): 発生した例外オブジェクト.

    Returns:
        float | None: 抽出された推奨待機秒数. 抽出できない場合は None.
    """
    err_str = str(e)
    match = re.search(r"retryDelay[\"']?\s*:\s*[\"']?(\d+(?:\.\d+)?)s", err_str)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return None


def _is_retryable_error(e: Exception) -> bool:
    """リトライ対象のエラー（503/429等）かどうかを判定します.

    Args:
        e (Exception): 検証対象の Gemini API 例外オブジェクト.

    Returns:
        bool: リトライ対象のエラーである場合は True, 400 Bad Request 等のリトライ不可エラーの場合は False.
    """
    err_str = str(e)

    # 1日あたりのクォータ超過 (RPD) は待機しても回復しないためリトライしない
    if "PerDay" in err_str or "GenerateRequestsPerDay" in err_str:
        logger.error("1日あたりの API 利用上限 (RPD) に到達しました.")
        return False

    # APIError, ServerError, ClientError すべてを対象
    if isinstance(e, (APIError, ServerError, ClientError)):
        code = getattr(e, "code", None) or getattr(e, "status_code", None)
        if code in (503, 429):
            return True

    err_msg = str(e).upper()
    return any(
        keyword in err_msg
        for keyword in ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED")
    )


def send_message_with_retry(
    chat: Any,
    prompt: str,
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
) -> Any:
    """Gemini API へのリクエストを送信し, 通信エラー発生時にリトライを行います.

    Args:
        chat (Any): Gemini Chat インスタンス.
        prompt (str): 送信するプロンプト文字列.
        max_retries (int, optional): 最大リトライ回数. デフォルトは 3.
        initial_delay (float, optional): 初回リトライ時の待ち時間（秒）. デフォルトは 1.0.
        backoff_factor (float, optional): 指数バックオフの倍率. デフォルトは 2.0.

    Returns:
        Any: Gemini API からのレスポンス.

    Raises:
        Exception: 最大リトライ回数を超えてエラーが発生した場合.
        AssertionError: 内部状態の不整合により例外オブジェクトが保持されなかった場合.
    """
    delay = initial_delay
    last_exception: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            return chat.send_message(prompt)

        except Exception as e:  # noqa: BLE001 # pylint: disable=broad-exception-caught
            last_exception = e
            if attempt == max_retries or not _is_retryable_error(e):
                break

            api_retry_delay = _extract_retry_delay(e)
            if api_retry_delay is not None:
                sleep_time = api_retry_delay + 1.0
            else:
                sleep_time = delay
                delay *= backoff_factor

            logger.warning(
                "Gemini API で一時的なエラーが発生しました (%d/%d): %s. %.1f秒後に再試行します...",
                attempt,
                max_retries,
                e,
                sleep_time,
            )
            time.sleep(sleep_time)

    # ここに到達した時点で last_exception は必ず存在する
    assert last_exception is not None  # 型チェッカーへの明示
    raise last_exception


def send_message_stream_with_retry(
    chat: Any,
    prompt: str,
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
) -> Iterator[Any]:
    """Gemini API へのストリーミングリクエストを送信し, 通信エラー発生時にリトライを行います.

    イテレーション中の API エラー（503/429等）もキャッチして再試行します.
    途中でエラーが発生した場合は画面に通知し, リトライ時は最初からメッセージを送り直します.

    Args:
        chat (Any): Gemini Chat インスタンス.
        prompt (str): 送信するプロンプト文字列.
        max_retries (int, optional): 最大リトライ回数. デフォルトは 3.
        initial_delay (float, optional): 初回リトライ時の待ち時間（秒）. デフォルトは 1.0.
        backoff_factor (float, optional): 指数バックオフの倍率. デフォルトは 2.0.

    Yields:
        Any: Gemini API からのレスポンスチャンク.

    Raises:
        APIError: 最大リトライ回数を超えてエラーが発生した場合.
    """
    delay = initial_delay

    for attempt in range(1, max_retries + 1):
        has_yielded_content = False

        try:
            response_stream = chat.send_message_stream(prompt)
            for chunk in response_stream:
                has_yielded_content = True  # チャンクをひとつでも送出したら True に変更
                yield chunk
            return  # 正常終了

        except Exception as e:  # pylint: disable=broad-exception-caught
            # 既にユーザーに画面出力が開始されている途中で切れた場合は,
            # 出力の重複を防ぐためリトライせずにエラーを送出する
            if (
                has_yielded_content
                or attempt == max_retries
                or not _is_retryable_error(e)
            ):
                error_detail = (
                    str(e) if logger.isEnabledFor(logging.DEBUG) else type(e).__name__
                )
                logger.error(
                    "ストリーミングの受信途中でエラーが発生しました（一部出力済みのためリトライ中断）: %s",
                    error_detail,
                )
                raise

            # API側から retryDelay の指定があれば優先, なければ指数バックオフ
            api_retry_delay = _extract_retry_delay(e)
            if api_retry_delay is not None:
                sleep_time = api_retry_delay + 1.0
            else:
                sleep_time = delay
                delay *= backoff_factor

            logger.warning(
                "Gemini API で一時的なエラーが発生しました (%d/%d): %s. %.1f秒後に再試行します...",
                attempt,
                max_retries,
                e,
                sleep_time,
            )
            time.sleep(sleep_time)


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
            handle_commit_msg_generation(client, cli_args.model)
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
