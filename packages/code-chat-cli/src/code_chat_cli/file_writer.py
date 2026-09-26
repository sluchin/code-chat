"""ファイル書き込みおよび変更の確認処理を管理するモジュール."""

import re
from datetime import UTC, datetime
from pathlib import Path

from code_chat_lib.logger import get_logger

logger = get_logger(__name__)

# マークダウンのコードブロック (` ```python ... ``` ` や ` ``` ... ``` `) を抽出する正規表現
CODE_BLOCK_PATTERN = re.compile(
    r"```(?:[a-zA-Z0-9_+\-#]+)?\n(?P<code>.*?\n?)```",
    re.DOTALL,
)

# 保持する最大バックアップ世代数
MAX_BACKUP_COUNT = 5


def handle_write_mode_confirmation(
    target_paths: list[str] | None, response_text: str
) -> None:
    """Write Mode 時に抽出したコードでファイルを更新します.

    抽出したコードの妥当性を検証し, ユーザーに確認を求めた上でファイルの上書きを行います.

    Args:
        target_paths (list[str] | None): 書き換え対象のファイルパスリスト.
        response_text (str): Gemini から返却されたレスポンス本文全体.

    """
    logger.debug(
        "handle_write_mode_confirmation 呼び出し - target_paths: %s", target_paths
    )

    if not target_paths:
        logger.error("対象のファイルパスが指定されていません.")
        return

    # 渡されたパスのうち, 存在するファイルのみを有効な対象として抽出
    valid_targets: list[Path] = []
    for p_str in target_paths:
        path = Path(p_str)
        if path.is_file():
            valid_targets.append(path)
        else:
            logger.warning("'%s' は存在しないか, 通常のファイルではありません.", p_str)

    if not valid_targets:
        logger.error("書き込み対象となる有効なファイルが存在しません.")
        return

    # レスポンスから (パス, コードブロック) のペアを抽出
    # 例: ```python:path/to/file.py ... ``` や ```path/to/file.py ... ```
    changes = _extract_file_changes(response_text, valid_targets)

    if not changes:
        logger.error(
            "レスポンスから書き込み可能なコードブロックを抽出できませんでした."
        )
        return

    # 変更対象ファイルとコードの検証・確認表示
    print("\n[Write Mode] 以下のファイルへの変更が提案されています:")
    for path_str, code in changes.items():
        line_count = len(code.splitlines())
        has_partial = _is_partial_code(code)
        warning_msg = " [省略の可能性あり]" if has_partial else ""
        print(f"  - {path_str} ({line_count} 行){warning_msg}")

        if has_partial:
            logger.warning(
                "'%s' の出力コード内に省略（'...' や '変更なし' 等）が含まれている可能性があります.",
                path_str,
            )

    confirm = (
        input("\n提案された内容で対象ファイルを上書きしますか？ (y/N): ")
        .strip()
        .lower()
    )

    logger.debug("ユーザー入力結果: '%s'", confirm)

    if confirm == "y":
        for path_str, code in changes.items():
            _apply_file_modification(path_str, code)
    else:
        print("上書きをキャンセルしました.")


def _apply_file_modification(target_path: str, new_code: str) -> None:
    """指定された単一ファイルへ修正後コードを書き込みます.

    安全なバックアップファイルを生成した上で,
    指定パスのファイルを新しい内容で上書きします.

    Args:
        target_path (str): 上書き対象のファイルパス.
        new_code (str): ファイルに書き込む新しいソースコード文字列.

    """
    path = Path(target_path)
    if not path.is_file():
        logger.error("'%s' は存在しないか, 単一ファイルではありません.", target_path)
        return

    try:
        # バックアップファイルの作成
        if path.exists():
            _create_safe_backup(path)

        # 新しいコードの書き込み
        path.write_text(new_code, encoding="utf-8")
        print(f"'{path}' を更新しました.")
    except OSError:
        logger.exception("ファイルの書き換えに失敗しました.")


def _create_safe_backup(path: Path) -> Path | None:
    """ファイルを安全にバックアップします.

    - 初回バックアップとして `.bak.orig` を保護作成します.
    - 実行ごとにタイムスタンプ付きのバックアップを作成します.
    - 古いタイムスタンプ付きバックアップは上限数を超えたら自動削除します.

    Args:
        path (Path): バックアップ対象のファイルパス.

    Returns:
        Path | None: 作成されたタイムスタンプ付きバックアップのパス.
            ファイルが存在しないか通常ファイルでない場合は None.

    Raises:
        OSError: タイムスタンプ付きバックアップの作成に失敗した場合.

    """
    if not path.exists() or not path.is_file():
        return None

    # 初回オリジナルの永久保存 (既に存在する場合は上書きしない)
    orig_bak = path.with_suffix(path.suffix + ".bak.orig")
    if not orig_bak.exists():
        try:
            orig_bak.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"初回オリジナルバックアップを作成しました: {orig_bak}")
        except OSError as e:
            logger.warning("オリジナルバックアップの作成に失敗しました: %s", e)

    # タイムスタンプ付きバックアップの作成 (ミリ秒含めて重複回避)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    ts_bak = path.with_suffix(f"{path.suffix}.bak.{timestamp}")

    try:
        ts_bak.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        logger.debug("タイムスタンプ付きバックアップを作成しました: %s", ts_bak)
    except OSError as e:
        logger.error("バックアップ作成に失敗しました: %s", e)
        raise

    # 古い世代のクリーンアップ (MAX_BACKUP_COUNT を超えたものを削除)
    _cleanup_old_backups(path, max_keep=MAX_BACKUP_COUNT)

    return ts_bak


def _is_partial_code(code: str) -> bool:
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


def _sanitize_code_output(raw_output: str) -> str:
    """LLM の出力テキストから純粋なソースコード部分のみを抽出・サニタイズします.

    LLM がコードブロックの外側に解説文（例: 'Here is the generated code:'）を
    含めている場合でも, 正規表現を用いて最初のコードブロック内部のコードのみを取り出します.
    コードブロック記号が存在しない場合は, 先頭の解説行をスキップして抽出を試みます.

    Args:
        raw_output (str): LLM から返却された生のテキスト出力.

    Returns:
        str: ファイルに書き込むためのサニタイズ済みソースコード.

    """
    if not raw_output:
        return ""

    text = raw_output.strip()

    # 正規表現でコードブロック (``` ... ```) を検索
    match = CODE_BLOCK_PATTERN.search(text)
    if match:
        return match.group("code").strip() + "\n"

    # コードブロック記号がない場合のフォールバック処理
    lines = text.splitlines()
    code_lines: list[str] = []
    is_code_started = False

    for line in lines:
        stripped = line.strip()

        # 先頭の解説文（英語・日本語の代表的な導入フレーズやコメントでない自然言語行）をスキップ
        if not is_code_started:
            # 既にコメント行やコードらしい記号で始まっている場合はコード開始とみなす
            if (
                stripped.startswith(
                    (
                        "#",
                        "//",
                        "/*",
                        "import ",
                        "from ",
                        "def ",
                        "class ",
                    )
                )
                or not stripped
            ):
                is_code_started = True
            elif stripped.endswith(":") and (
                "code" in stripped.lower() or "以下" in stripped or "コード" in stripped
            ):
                # "Here is the code:" や "以下のコードです:" のような解説行をスキップ
                continue
            else:
                is_code_started = True

        if is_code_started:
            code_lines.append(line)

    sanitized = "\n".join(code_lines).strip()
    return f"{sanitized}\n" if sanitized else ""


def _cleanup_old_backups(path: Path, max_keep: int) -> None:
    """指定された世代数を超えた古いタイムスタンプ付きバックアップファイルを削除します.

    `.bak.orig` (初回オリジナルバックアップ) は削除対象から除外し,
    タイムスタンプの古い順にソートして上限数 `max_keep` を超えるファイルを削除します.

    Args:
        path (Path): バックアップ対象の元ファイルパス.
        max_keep (int): 保持するタイムスタンプ付きバックアップの最大世代数.

    """
    pattern = f"{path.name}.bak.*"
    # *.bak.orig 以外のタイムスタンプ付きバックアップを抽出
    backups = [
        p
        for p in path.parent.glob(pattern)
        if not p.name.endswith(".bak.orig") and p.is_file()
    ]

    # 作成日時（名前順でもタイムスタンプ順になる）でソート
    backups.sort(key=lambda p: p.name)

    # 保持件数を超えた古いファイルを削除
    if len(backups) > max_keep:
        for old_bak in backups[:-max_keep]:
            try:
                old_bak.unlink()
                logger.debug("古いバックアップを削除しました: %s", old_bak)
            # 削除に失敗しても, 次回のバックアップ作成時に再び整理されるため, 無視する
            except OSError:
                pass


def _extract_file_changes(
    response_text: str, valid_targets: list[Path]
) -> dict[str, str]:
    """レスポンス本文からパスとコードブロックの対応辞書を抽出します.

    Args:
        response_text (str): Gemini から返却されたレスポンス本文全体.
        valid_targets (list[Path]): 書き換え対象の有効なファイルパスリスト.

    Returns:
        dict[str, str]: ファイルパスをキー, 抽出されたコードブロックを値とする辞書.

    """
    # 相対パスと絶対パスの表記の違いを吸収するため, 絶対パスで照合する
    valid_str_paths = {str(p.resolve()): str(p) for p in valid_targets}
    changes: dict[str, str] = {}

    # パス付きコードブロックのパターン検索 (例: ```python:src/a.py または ```src/a.py)
    pattern = r"```(?:[\w+-]+:)?([^\n]+)\n(.*?)```"
    matches = re.findall(pattern, response_text, re.DOTALL)

    for path_hint, code_block in matches:
        path_hint = path_hint.strip()
        cleaned_code = _sanitize_code_output(code_block)

        if not cleaned_code.strip():
            continue

        # ヘッダーに指定されたパスが valid_targets に含まれているか照合
        resolved_hint = str(Path(path_hint).resolve())
        if resolved_hint in valid_str_paths:
            original_path = valid_str_paths[resolved_hint]
            changes[original_path] = cleaned_code

    # パスが明記されていない単一コードブロックの場合（対象が1つだけのフォールバック）
    if not changes and len(valid_targets) == 1:
        single_code = _sanitize_code_output(response_text)
        if single_code.strip():
            changes[str(valid_targets[0])] = single_code

    return changes
