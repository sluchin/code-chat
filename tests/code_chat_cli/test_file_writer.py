"""ファイル書き込みおよび変更の確認処理モジュールの単体テスト."""

import time
from pathlib import Path
from unittest.mock import patch

import pytest
from code_chat_cli.file_writer import (
    _cleanup_old_backups,
    _is_partial_code,
    _sanitize_code_output,
    apply_file_modification,
    create_safe_backup,
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

    bak_orig = tmp_path / "sample.py.bak.orig"
    assert bak_orig.exists()

    # タイムスタンプ付きバックアップの存在確認 (glob検索など)
    bak_files = list(tmp_path.glob("sample.py.bak.*"))
    assert len(bak_files) >= 1


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


def test_create_safe_backup_not_exists(tmp_path: Path) -> None:
    """存在しないファイルパスを指定した場合、None が返されること."""
    non_existent_path = tmp_path / "non_existent.py"

    result = create_safe_backup(non_existent_path)

    assert result is None


def test_create_safe_backup_is_directory(tmp_path: Path) -> None:
    """ファイルではなくディレクトリパスを指定した場合、None が返されること."""
    dir_path = tmp_path / "test_dir"
    dir_path.mkdir()

    result = create_safe_backup(dir_path)

    assert result is None


def test_extract_code_block_fallback_with_intro_phrase() -> None:
    """コードブロック記号がなく、先頭に解説文（"Here is the code:" など）が含まれる場合のフォールバック抽出を検証."""
    text = (
        "Here is the code:\n"  # 253-255行目の continue を通過
        "\n"  # 250行目 (not stripped)
        "# This is a comment\n"  # 249行目 (startswith("#"))
        "import os\n"  # 249行目 (startswith("import "))
        "def main():\n"
        "    pass\n"
    )

    result = _sanitize_code_output(text)

    expected = "# This is a comment\nimport os\ndef main():\n    pass\n"
    assert result == expected


def test_extract_code_block_fallback_direct_code() -> None:
    """コードブロック記号がなく、解説文なしで通常のテキストからコードが開始する場合を検証."""
    text = (
        "Some general explanation text\n"  # 256-257行目の else (is_code_started = True) を通過
        "print('hello')\n"
    )

    result = _sanitize_code_output(text)

    expected = "Some general explanation text\nprint('hello')\n"
    assert result == expected


def test_extract_code_block_fallback_empty_result() -> None:
    """コード部分が存在せず空文字が返される場合（263行目の else 判定）を検証."""
    text = "Here is the code:\n"  # 全行スキップされて sanitized が空になる

    result = _sanitize_code_output(text)

    assert result == ""


def test_cleanup_old_backups_exceeds_max_keep(tmp_path: Path) -> None:
    """古いバックアップファイル数が上限を超えた場合、超過分が正常に削除されることを検証."""
    target_file = tmp_path / "test.py"
    target_file.write_text("content", encoding="utf-8")

    # 例: max_keep が 3 の場合、4つのバックアップファイルを作成
    backup_files = []
    for i in range(4):
        # タイムスタンプ順になるようソート可能な名前で作成
        bak = tmp_path / f"test.py.bak.20260907_10000{i}"
        bak.write_text(f"backup {i}", encoding="utf-8")
        backup_files.append(bak)
        time.sleep(0.01)

    # _cleanup_old_backups を実行 (max_keep=3 を指定)
    _cleanup_old_backups(target_file, max_keep=3)

    # 最も古い backup_files[0] のみが削除されていること
    assert not backup_files[0].exists()
    assert backup_files[1].exists()
    assert backup_files[2].exists()
    assert backup_files[3].exists()


def test_cleanup_old_backups_unlink_os_error(tmp_path: Path) -> None:
    """古いバックアップファイルの削除中に OSError が発生しても例外をキャッチして継続することを検証."""
    target_file = tmp_path / "test.py"
    target_file.write_text("content", encoding="utf-8")

    # max_keep を超える2つのバックアップを作成
    bak1 = tmp_path / "test.py.20260907_100001.bak"
    bak2 = tmp_path / "test.py.20260907_100002.bak"
    bak1.write_text("old", encoding="utf-8")
    bak2.write_text("new", encoding="utf-8")

    # unlink 呼び出し時に OSError を発生させる
    with patch.object(Path, "unlink", side_effect=OSError("Permission denied")):
        # 例外がスルーされずに正常終了することを確認
        _cleanup_old_backups(target_file, max_keep=1)


def test_cleanup_old_backups_os_error_handled(tmp_path: Path) -> None:
    """古いバックアップ削除時に OSError が発生しても例外をキャッチして処理が継続することを検証."""
    target_file = tmp_path / "test.py"
    target_file.write_text("initial content", encoding="utf-8")

    # 実際にバックアップファイルをディスクに作成する
    # (※プロダクトコードの命名規則に合わせて .bak などの拡張子を調整してください)
    for i in range(4):
        bak = tmp_path / f"test.py.bak.20260907_10000{i}"
        bak.write_text(f"backup {i}", encoding="utf-8")

    # module 側の Path.unlink を失敗させる
    with patch(
        "code_chat_cli.file_writer.Path.unlink",
        side_effect=OSError("Permission denied"),
    ):
        # 例外が発生しても例外が送出されず正常終了することを確認
        _cleanup_old_backups(target_file, max_keep=1)
