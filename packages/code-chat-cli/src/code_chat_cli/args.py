"""Gemini CLI Tool - Argument Parser and Context Collector.

This module parses command-line arguments and collects context from files or standard input
for the Gemini CLI application.
"""

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from code_chat_cli.constants import EXCLUDE_DIRS, TEXT_EXTENSIONS
from code_chat_cli.logger import get_logger

logger = get_logger(__name__)

SUBCOMMANDS = {"index", "ask"}

# 値をとるオプション（パラメータ付きフラグ）の集合
OPTIONS_WITH_VALUE = {
    "-f",
    "--file",
    "-o",
    "--output",
    "-m",
    "--model",
    "--log-level",
    "-r",
    "--repo-path",
    "-k",
    "--top-k",
}


# pylint: disable=too-many-instance-attributes
@dataclass
class CliArgs:
    """解析済み引数とコンテキスト情報を保持するデータクラス."""

    prompt: str
    """ユーザーが指定した初期プロンプト文字列."""

    target_path: str | None
    """`-f`/`--file` で指定された参照パス."""

    output_path: str | None
    """`-o`/`--output` で指定されたログ保存先パス."""

    auto_save: bool
    """`-s`/`--auto-save` による自動保存の有効化フラグ."""

    write_mode: bool
    """`-w`/`--write` によるソースコード直接修正モードの有効化フラグ."""

    model: str
    """使用する Gemini モデル名."""

    debug: bool
    """デバッグモード."""

    log_level: str
    """ログレベル文字列."""

    list_models: bool
    """モデル一覧表示."""

    generate_commit_msg: bool
    """コミットメッセージ生成."""

    review: bool

    staged: bool

    context: str
    """読み込まれた標準入力およびファイルコンテキストの結合文字列."""

    command: str | None = None
    """実行する RAG サブコマンド ('index' / 'ask' / None)."""

    repo_path: str = "."
    """RAG 対象のリポジトリパス."""

    query: str | None = None
    """RAG `ask` サブコマンド指定時の検索クエリ."""

    top_k: int = 5
    """RAG `ask` サブコマンド指定時の検索取得件数."""


def read_path_content(target_path: str) -> str:
    """指定されたパス（単一ファイルまたはディレクトリ）からコンテンツを読み込む.

    ディレクトリが指定された場合は再帰的に探索し, 対象の拡張子を持つファイルの内容を
    除外ディレクトリを回避しながら結合して返します.

    Args:
        target_path: 読み込み対象のファイルまたはディレクトリのパス.

    Returns:
        読み込まれたファイル内容のテキスト. 該当ファイルが存在しない場合は空文字列.

    Raises:
        SystemExit: 指定されたパスが存在しない場合, またはファイルの読み込みに失敗した場合に
            ステータスコード 1 で終了します.
    """
    path = Path(target_path)

    if not path.exists():
        logger.error("パス '%s' が見つかりません.", target_path)
        sys.exit(1)

    if path.is_file():
        try:
            return f"=== File: {path} ===\n" + path.read_text(encoding="utf-8")
        except OSError:
            logger.exception("ファイル '%s' の読み込みに失敗しました", path)
            sys.exit(1)

    if path.is_dir():
        contents: list[str] = []

        # os.walk を使うことで除外ディレクトリ配下の走査を即座にスキップ可能
        for root, dirs, files in os.walk(path):
            # EXCLUDE_DIRS に含まれるディレクトリ配下を走査対象から除外
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

            for file in files:
                file_path = Path(root) / file
                if file_path.suffix.lower() in TEXT_EXTENSIONS:
                    try:
                        text = file_path.read_text(encoding="utf-8", errors="ignore")
                        contents.append(f"=== File: {file_path} ===\n{text}")
                    except OSError as e:
                        logger.warning(
                            "'%s' の読み込みをスキップしました: %s",
                            file_path,
                            e,
                        )

        if not contents:
            logger.warning(
                "ディレクトリ '%s' 内に対象ファイルが見つかりませんでした.",
                target_path,
            )
            return ""

        return "\n\n".join(contents)

    return ""


def read_stdin_content() -> str:
    """標準入力（パイプやリダイレクト）からテキストを読み込む.

    Returns:
        標準入力から読み込まれたテキスト. 端末（tty）からの入力である場合は空文字列.
    """
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return ""


# pylint: disable=too-many-locals,too-many-statements
def parse_args(args: list[str] | None = None) -> CliArgs:
    """コマンドライン引数を解析し, コンテキストを取得して返す.

    標準入力および `-f`/`--file` オプション経由で指定されたコンテキスト情報を収集し,
    解析済みデータクラス `CliArgs` にまとめて返却します.

    Args:
        args: 解析対象のコマンドライン引数リスト. None の場合は `sys.argv[1:]` を参照します.

    Returns:
        解析済みのコマンドライン引数と収集されたコンテキストを保持する `CliArgs` オブジェクト.
    """
    if args is None:
        args = sys.argv[1:]

    prompt_parts: list[str] = []
    filtered_args: list[str] = []
    has_subcommand = False

    i = 0
    while i < len(args):
        arg = args[i]

        if arg in SUBCOMMANDS:
            has_subcommand = True
            filtered_args.append(arg)
            i += 1
        elif arg.startswith("-"):
            filtered_args.append(arg)
            # `--log-level debug` のように値を取るオプションの場合は直後の引数もそのまま保存する
            if arg in OPTIONS_WITH_VALUE and i + 1 < len(args):
                i += 1
                filtered_args.append(args[i])
            i += 1
        elif not has_subcommand:
            prompt_parts.append(arg)
            i += 1
        else:
            filtered_args.append(arg)
            i += 1

    prompt = " ".join(prompt_parts)

    parser = argparse.ArgumentParser(description="Gemini API を使った CLI ツール")

    parser.add_argument(
        "-f",
        "--file",
        type=str,
        help="参照するファイルまたはディレクトリのパス",
        default=None,
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        help="指定したファイル名で対話ログを保存",
        default=None,
    )
    parser.add_argument(
        "-s",
        "--auto-save",
        action="store_true",
        help="対話内容からタイトルを自動生成して保存",
    )
    parser.add_argument(
        "-w",
        "--write",
        action="store_true",
        help="Gemini によるソースコードの直接修正・書き換えを許可するモード",
    )
    parser.add_argument(
        "-m",
        "--model",
        type=str,
        default="gemini-flash-latest",
        help="使用する Gemini モデル名 (デフォルト: gemini-flash-latest)",
    )
    # デバッグフラグ (-D / --debug)
    parser.add_argument(
        "-D",
        "--debug",
        action="store_true",
        help="デバッグモードを有効にします（--log-level DEBUG と同等）",
    )
    parser.add_argument(
        "--log-level",
        type=str.upper,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="ログレベルを指定します (デフォルト: INFO)",
    )
    parser.add_argument(
        "-l",
        "--list-models",
        action="store_true",
        help="利用可能なモデルの一覧を表示して終了します",
    )
    parser.add_argument(
        "-g",
        "--generate-commit-msg",
        action="store_true",
        help="git diff (--cached) からコミットメッセージ案を生成します",
    )
    parser.add_argument(
        "-r",
        "--review",
        action="store_true",
        help="git diff または指定ファイルの内容をコードレビューします.",
    )
    parser.add_argument(
        "--staged",
        action="store_true",
        help="--review または --generate-commit-msg 実行時に staged 状態の差分を対象にします.",
    )

    # RAG サブコマンド
    subparsers = parser.add_subparsers(dest="command", help="RAG サブコマンド")

    index_parser = subparsers.add_parser(
        "index", help="リポジトリの RAG インデックスを作成します"
    )
    index_parser.add_argument(
        "--repo-path",
        "-r",
        default=".",
        help="対象リポジトリのパス (デフォルト: カレントディレクトリ)",
    )

    ask_parser = subparsers.add_parser(
        "ask", help="RAG を使ってリポジトリのコードベースに質問します"
    )
    ask_parser.add_argument("query", type=str, help="検索クエリ")
    ask_parser.add_argument(
        "--repo-path",
        "-r",
        default=".",
        help="対象リポジトリのパス (デフォルト: カレントディレクトリ)",
    )
    ask_parser.add_argument(
        "--top-k",
        "-k",
        type=int,
        default=5,
        help="取得するコンテキストの件数 (デフォルト: 5)",
    )

    raw_args = parser.parse_args(filtered_args)

    # コンテキストの収集
    context_parts: list[str] = []

    # パイプからの入力を取得
    stdin_text = read_stdin_content()
    if stdin_text:
        context_parts.append(f"--- [標準入力] ---\n{stdin_text}")

    # -f オプションからの入力を取得
    if raw_args.file:
        path_text = read_path_content(raw_args.file)
        if path_text:
            context_parts.append(f"--- [パス入力: {raw_args.file}] ---\n{path_text}")

    context_str = "\n\n".join(context_parts)

    return CliArgs(
        prompt=prompt,
        target_path=raw_args.file,
        output_path=raw_args.output,
        auto_save=raw_args.auto_save,
        write_mode=raw_args.write,
        model=raw_args.model,
        debug=raw_args.debug,
        log_level=raw_args.log_level,
        list_models=raw_args.list_models,
        generate_commit_msg=raw_args.generate_commit_msg,
        review=raw_args.review,
        staged=raw_args.staged,
        context=context_str,
        command=raw_args.command,
        repo_path=getattr(raw_args, "repo_path", "."),
        query=getattr(raw_args, "query", None),
        top_k=getattr(raw_args, "top_k", 5),
    )
