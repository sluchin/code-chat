"""ファイル書き込みおよび変更の確認処理を管理するモジュール."""

import re
from datetime import UTC, datetime
from pathlib import Path

from code_chat_cli.logger import get_logger

logger = get_logger(__name__)

# マークダウンのコードブロック (` ```python ... ``` ` や ` ``` ... ``` `) を抽出する正規表現
CODE_BLOCK_PATTERN = re.compile(
    r"```(?:[a-zA-Z0-9_+\-#]+)?\n(?P<code>.*?\n?)```",
    re.DOTALL,
)

# 保持する最大バックアップ世代数
MAX_BACKUP_COUNT = 5


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

    code = _sanitize_code_output(response_text)
    logger.debug("抽出結果コード長: %d 文字", len(code))

    if not code.strip():
        logger.error(
            "レスポンスから書き込み可能なコードブロックを抽出できませんでした."
        )
        return

    if _is_partial_code(code):
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
        if path.exists():
            create_safe_backup(path)

        # 新しいコードの書き込み
        path.write_text(new_code, encoding="utf-8")
        logger.info("'%s' を更新しました.", path)
    except OSError:
        logger.exception("ファイルの書き換えに失敗しました.")


def create_safe_backup(path: Path) -> Path | None:
    """ファイルを安全にバックアップします.

    - 初回バックアップとして `.bak.orig` を保護作成します.
    - 実行ごとにタイムスタンプ付きのバックアップを作成します.
    - 古いタイムスタンプ付きバックアップは上限数を超えたら自動削除します.

    Args:
        path (Path): バックアップ対象のファイルパス.

    Returns:
        Path | None: 作成されたタイムスタンプ付きバックアップのパス.
            ファイルが存在しない場合は None.
    """
    if not path.exists() or not path.is_file():
        return None

    # 初回オリジナルの永久保存 (既に存在する場合は上書きしない)
    orig_bak = path.with_suffix(path.suffix + ".bak.orig")
    if not orig_bak.exists():
        try:
            orig_bak.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            logger.info("初回オリジナルバックアップを作成しました: %s", orig_bak)
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
                        "p",
                        "u",
                        "v",
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
            except OSError:
                pass
