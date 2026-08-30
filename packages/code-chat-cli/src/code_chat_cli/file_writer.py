"""ファイル書き込みおよび変更の確認処理を管理するモジュール."""

import re
from pathlib import Path

from code_chat_cli.logger import get_logger

logger = get_logger(__name__)


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


def _sanitize_code_output(text: str) -> str:
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
