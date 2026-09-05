"""ファイル書き込みおよび変更の確認処理モジュールの単体テスト."""

from pathlib import Path
from unittest.mock import patch

import pytest
from code_chat_cli.file_writer import (
    _is_partial_code,
    apply_file_modification,
    handle_write_mode_confirmation,
)


@pytest.mark.parametrize(
    "code_input",
    [
        "// ...",
        "//...",
        "# ...",
        "#...",
        "# 既存のコード",
        "// 既存のコード",
        "// 変更なし",
        "# 変更なし",
        "// rest of code",
        "# REST OF CODE",  # 大文字小文字（re.IGNORECASE）の検証
    ],
)
def test_is_partial_code_returns_true(code_input):
    """省略表現やプレースホルダーコメントが含まれている場合, True が返るか検証."""
    sample_code = f"""
def main():
    {code_input}
    return 0
"""
    assert _is_partial_code(sample_code) is True


def test_is_partial_code_returns_false():
    """省略表現が含まれない完全なソースコードの場合, False が返るか検証."""
    complete_code = """
def add(a: int, b: int) -> int:
    # 2つの数値の和を計算する
    return a + b
"""
    assert _is_partial_code(complete_code) is False


def test_apply_file_modification_success(tmp_path):
    """正常系: .bak バックアップが作成され, 元ファイルが新しい内容で上書きされるか検証."""
    target_file = tmp_path / "sample.py"
    target_file.write_text("original_code", encoding="utf-8")

    new_code = "updated_code"
    apply_file_modification(str(target_file), new_code)

    # バックアップファイル (.py.bak) が作成され, 元の内容が保存されていること
    bak_file = tmp_path / "sample.py.bak"
    assert bak_file.exists()
    assert bak_file.read_text(encoding="utf-8") == "original_code"

    # 対象ファイルが新しいコードで更新されていること
    assert target_file.read_text(encoding="utf-8") == new_code


def test_apply_file_modification_not_a_file(tmp_path):
    """異常系: パスが存在しない, またはディレクトリの場合, 早期リターンして何も処理しないか検証."""
    non_existent_file = tmp_path / "non_existent.py"

    # 存在しないパスを指定（ログを出力して終了）
    apply_file_modification(str(non_existent_file), "new_code")

    bak_file = tmp_path / "non_existent.py.bak"
    assert not non_existent_file.exists()
    assert not bak_file.exists()


def test_apply_file_modification_exception(tmp_path):
    """異常系: 書き込み時に Exception が発生した場合, except ブロックでキャッチされログが出力されるか検証."""
    target_file = tmp_path / "sample.py"
    target_file.write_text("original_code", encoding="utf-8")

    # read_text または write_text で例外を発生させる
    with patch.object(Path, "write_text", side_effect=OSError("Write error")):
        # 例外を発生させても関数内部で catch されるため, エラー無く終了することを確認
        apply_file_modification(str(target_file), "new_code")


def test_handle_write_mode_confirmation_none_target_path():
    """target_path_str が None の場合, 早期リターンすること（エラーログのみ）."""
    # パス未指定時は何も実行せず終了
    handle_write_mode_confirmation(None, "```python\nprint('hello')\n```")


def test_handle_write_mode_confirmation_invalid_file(tmp_path):
    """存在しないファイルまたはディレクトリが指定された場合, 早期リターンすること."""
    non_existent = tmp_path / "non_existent.py"
    handle_write_mode_confirmation(str(non_existent), "```python\nprint('hello')\n```")


def test_handle_write_mode_confirmation_no_code_extracted(tmp_path):
    """レスポンスからコードが抽出できない場合, 早期リターンすること."""
    target_file = tmp_path / "target.py"
    target_file.write_text("print('old')", encoding="utf-8")

    # 空レスポンスを渡す
    handle_write_mode_confirmation(str(target_file), "")

    # ファイルが変更されていないこと
    assert target_file.read_text(encoding="utf-8") == "print('old')"


def test_handle_write_mode_confirmation_user_accepts(monkeypatch, tmp_path):
    """ユーザーが 'y' と入力した場合, apply_file_modification が呼び出されて上書きされるか検証."""
    target_file = tmp_path / "target.py"
    target_file.write_text("print('old')", encoding="utf-8")

    response_text = "```python\nprint('new')\n```"

    # input() の返り値を 'y' にモック
    monkeypatch.setattr("builtins.input", lambda _: "y")

    handle_write_mode_confirmation(str(target_file), response_text)

    # ファイルが上書き更新されていること
    assert target_file.read_text(encoding="utf-8") == "print('new')\n"


def test_handle_write_mode_confirmation_user_declines(monkeypatch, tmp_path):
    """ユーザーが 'n' など 'y' 以外を入力した場合, 上書きがキャンセルされるか検証."""
    target_file = tmp_path / "target.py"
    target_file.write_text("print('old')", encoding="utf-8")

    response_text = "```python\n# 既存のコード\nprint('new')\n```"

    # input() の返り値を 'n' にモック
    monkeypatch.setattr("builtins.input", lambda _: "n")

    handle_write_mode_confirmation(str(target_file), response_text)

    # ファイルが上書きされていないこと
    assert target_file.read_text(encoding="utf-8") == "print('old')"
