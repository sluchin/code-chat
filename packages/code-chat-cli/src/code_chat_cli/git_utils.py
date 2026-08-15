"""Git コマンドの実行、リポジトリ状態の検証、および差分（diff）情報の取得を行うユーティリティモジュール."""

import subprocess
from logging import getLogger

logger = getLogger(__name__)


def get_git_diff() -> str:
    """Git の変更差分 (diff) を取得する.

    ステージング済み (--cached) の差分を優先し、なければ作業ディレクトリの差分を取得する.
    """
    try:
        # まずステージング済みの差分を確認
        diff = subprocess.check_output(
            ["git", "diff", "--cached"], text=True, encoding="utf-8"
        )

        # ステージング済みの差分がなければ、作業ツリーの差分を取得
        if not diff.strip():
            diff = subprocess.check_output(["git", "diff"], text=True, encoding="utf-8")

        return diff.strip()
    except subprocess.CalledProcessError:
        logger.error(
            "git diff の実行に失敗しました.Git リポジトリ内か確認してください."
        )
        raise
    except FileNotFoundError:
        logger.error("git コマンドが見つかりません.")
        raise
