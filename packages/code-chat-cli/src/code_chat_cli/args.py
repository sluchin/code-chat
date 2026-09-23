"""Code Chat CLI - 引数パーサーおよびコンテキストコレクター.

このモジュールは, Code Chat CLI アプリケーションのためにコマンドライン引数を解析し,
ファイルまたは標準入力からコンテキストを収集します.
"""

import argparse
import sys
from dataclasses import dataclass, field

from code_chat_cli.file_utils import read_path_content
from code_chat_cli.logger import get_logger

logger = get_logger(__name__)


# pylint: disable=too-many-instance-attributes
@dataclass
class CliArgs:
    """解析済み引数とコンテキスト情報を保持するデータクラス."""

    subcommand: str | None = None
    """実行するサブコマンド ('rag' / 'cache' / 'mcp' / None)."""

    subcommand_action: str | None = None
    """サブコマンド内のアクション ('create' / 'update' / 'rm' / 'status' / 'list' / 'run' / 'test')."""

    subcommand_target: str | None = None
    """サブコマンドの対象パスや識別子 (PATH / CACHE_ID / SERVER_NAME)."""

    # メイン対話・共通オプション
    prompt: str | None = None
    """ユーザーが指定した初期プロンプト文字列."""

    files: list[str] = field(default_factory=list)
    """`-f`/`--file` で指定された参照ファイル・ディレクトリパス."""

    rag: bool = False
    """`--rag` による RAG コンテキスト注入の有効化フラグ."""

    mcp: bool = False
    """`--mcp` による MCP 連携の有効化フラグ."""

    cache: bool | str = False
    """`-c`/`--cache` による Context Caching 利用指定 (True または Cache ID 文字列)."""

    model: str = "gemini-3.5-flash"
    """使用するモデル名."""

    provider: str = "gemini"
    """使用する LLM プロバイダ名 ('gemini' / 'claude' / 'openai' / 'local')."""

    write_mode: bool = False
    """`-w`/`--write` によるソースコード直接修正モードの有効化フラグ."""

    auto_save: bool = False
    """`-a`/`--auto-save` による自動保存の有効化フラグ."""

    context: str | None = None
    """読み込まれた標準入力およびファイルコンテキストの結合文字列."""

    # cache サブコマンド専用オプション
    cache_ttl: int = 3600
    """`cache` コマンド用: キャッシュ保持時間 (秒)."""

    # ログ・デバッグ用
    debug_mode: bool = False
    """デバッグモード有効化フラグ."""

    log_level: str | None = None
    """ログレベル文字列."""

    trace_mode: bool = False
    """サードパーティ製ライブラリのトランスポートログ制御."""

    dry_run: bool = False
    """ドライラン（実行処理の事前検証・試行）フラグ."""

    list_models: bool = False
    """モデル一覧表示フラグ."""

    generate_commit_msg: bool = False
    """コミットメッセージ生成フラグ."""

    review: bool = False
    """`--review` によるコードレビュー・静的解析モードフラグ."""

    # rag サブコマンド固有フラグ
    input_dirs: list[str] = field(default_factory=list)
    """インデックス作成対象のディレクトリパス"""

    output_dir: str | None = "./.chroma_db"
    """インデックス出力ディレクトリパス"""


# pylint: disable=too-many-locals,too-many-statements
def parse_args(args: list[str] | None = None) -> CliArgs:
    """コマンドライン引数を解析し, コンテキストを取得して返す."""
    if args is None:
        args = sys.argv[1:]

    global_parser = _build_global_parser()
    main_parser = _build_main_execution_parser(global_parser)

    # サブコマンド定義
    subparsers = main_parser.add_subparsers(
        dest="subcommand", help="管理用サブコマンド"
    )

    # RAG 管理サブコマンド
    rag_parser = subparsers.add_parser(
        "rag", parents=[global_parser], help="RAG インデックス管理"
    )
    rag_subparsers = rag_parser.add_subparsers(
        dest="subcommand_action", help="RAG アクション"
    )

    rag_create = rag_subparsers.add_parser(
        "create", parents=[global_parser], help="Vector DB を作成"
    )
    rag_create.add_argument(
        "--input_dirs", type=list[str], default=["."], help="入力パス (デフォルト: .)"
    )
    rag_create.add_argument(
        "--output_dir",
        type=str,
        default="./.chroma_db",
        help="出力パス (デフォルト: ./.chroma_db)",
    )

    rag_update = rag_subparsers.add_parser(
        "update", parents=[global_parser], help="差分インデックスを更新"
    )
    rag_update.add_argument(
        "--input_dirs", type=list[str], default=["."], help="入力パス (デフォルト: .)"
    )
    rag_update.add_argument(
        "--output_dir",
        type=str,
        default="./.chroma_db",
        help="出力パス (デフォルト: ./.chroma_db)",
    )

    rag_subparsers.add_parser("rm", parents=[global_parser], help="Vector DB を削除")
    rag_subparsers.add_parser(
        "status", parents=[global_parser], help="DB ステータスを表示"
    )

    # Cache 管理サブコマンド
    cache_parser = subparsers.add_parser(
        "cache", parents=[global_parser], help="Context Caching 管理"
    )
    cache_subparsers = cache_parser.add_subparsers(dest="subcommand_action")

    cache_create = cache_subparsers.add_parser(
        "create", parents=[global_parser], help="新規キャッシュを作成"
    )
    cache_create.add_argument(
        "target", nargs="?", default=".", help="対象パス (デフォルト: .)"
    )
    cache_create.add_argument(
        "--ttl", type=int, default=3600, help="保持時間(秒) (デフォルト: 3600)"
    )

    cache_update = cache_subparsers.add_parser(
        "update", parents=[global_parser], help="キャッシュを更新・再作成"
    )
    cache_update.add_argument(
        "target", nargs="?", default=".", help="対象パス (デフォルト: .)"
    )

    cache_rm = cache_subparsers.add_parser(
        "rm", parents=[global_parser], help="指定したキャッシュを削除"
    )
    cache_rm.add_argument(
        "target", nargs="?", default=None, help="Cache ID (省略時はすべて)"
    )

    cache_subparsers.add_parser(
        "list", parents=[global_parser], help="アクティブなキャッシュ一覧を表示"
    )

    # MCP 管理サブコマンド
    mcp_parser = subparsers.add_parser(
        "mcp", parents=[global_parser], help="MCP サーバー管理"
    )
    mcp_subparsers = mcp_parser.add_subparsers(dest="subcommand_action")

    mcp_run = mcp_subparsers.add_parser(
        "run", parents=[global_parser], help="指定した MCP サーバーを個別起動"
    )
    mcp_run.add_argument("target", help="サーバー名")

    mcp_subparsers.add_parser(
        "status", parents=[global_parser], help="MCP サーバーの接続状態を表示"
    )

    mcp_test = mcp_subparsers.add_parser(
        "test", parents=[global_parser], help="MCP サーバーの導通テスト"
    )
    mcp_test.add_argument(
        "target", nargs="?", default=None, help="サーバー名 (省略時はすべて)"
    )

    # パース処理
    # parse_known_args を使用して定義済みフラグ/サブコマンドと, 位置引数(prompt)を分離
    raw_args, unparsed_args = main_parser.parse_known_args(args)

    # 管理用サブコマンドでない場合は unparsed_args を prompt として扱う
    if raw_args.subcommand in ("rag", "cache", "mcp"):
        prompt_str = ""
    else:
        prompt_str = " ".join(unparsed_args) if unparsed_args else ""

    context_parts: list[str] = []

    # 標準入力の取得
    stdin_text = _read_stdin_content()
    if stdin_text:
        context_parts.append(f"--- [標準入力] ---\n{stdin_text}")

    # -f, --file オプションのテキスト読み込み
    file_targets: list[str] = getattr(raw_args, "files", None) or []
    if isinstance(file_targets, str):
        file_targets = [file_targets]

    for target in file_targets:
        if target:
            path_text = read_path_content(target)
            if path_text:
                context_parts.append(f"--- [パス入力: {target}] ---\n{path_text}")

    context_str = "\n\n".join(context_parts)

    # --input オプション (重複削除)
    raw_input_dirs = getattr(raw_args, "input_dirs", None)
    input_dirs = (
        list(dict.fromkeys(raw_input_dirs)) if raw_input_dirs is not None else ["."]
    )

    # ログレベルとデバッグモードの設定同期
    debug_mode = getattr(raw_args, "debug_mode", False)
    log_level = getattr(raw_args, "log_level", "INFO")
    if debug_mode or log_level == "DEBUG":
        debug_mode = True
        log_level = "DEBUG"

    trace_mode = bool(getattr(raw_args, "trace_mode", False) or "--trace" in args)

    return CliArgs(
        subcommand=getattr(raw_args, "subcommand", None),
        subcommand_action=getattr(raw_args, "subcommand_action", None),
        subcommand_target=getattr(raw_args, "target", None),
        prompt=prompt_str,
        files=file_targets,
        rag=getattr(raw_args, "rag", False),
        mcp=getattr(raw_args, "mcp", False),
        cache=getattr(raw_args, "cache", False),
        model=getattr(raw_args, "model", "gemini-3.5-flash"),
        provider=getattr(raw_args, "provider", "gemini"),
        write_mode=getattr(raw_args, "write_mode", False),
        auto_save=getattr(raw_args, "auto_save", False),
        context=context_str,
        cache_ttl=getattr(raw_args, "ttl", 3600),
        debug_mode=debug_mode,
        log_level=log_level,
        trace_mode=trace_mode,
        dry_run=getattr(raw_args, "dry_run", False),
        list_models=getattr(raw_args, "list_models", False),
        generate_commit_msg=getattr(raw_args, "generate_commit_msg", False),
        review=getattr(raw_args, "review", False),
        input_dirs=input_dirs,
        output_dir=getattr(raw_args, "output_dir", "./.chroma_db"),
    )


def _build_global_parser() -> argparse.ArgumentParser:
    """すべてのサブコマンドおよびメイン対話で共有される基本オプションを定義."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="API 呼び出しを行わず, 読み込まれるファイル群や指定引数の確認のみ実行します",
    )
    parser.add_argument(
        "-D",
        "--debug",
        action="store_true",
        dest="debug_mode",
        help="デバッグモードを有効にします（--log-level DEBUG と同等）",
    )
    parser.add_argument(
        "--log-level",
        type=str.upper,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        dest="log_level",
        help="ログレベルを指定します (デフォルト: INFO)",
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        dest="trace_mode",
        help="SDK や HTTP クライアント等のライブラリ内部通信ログを出力します",
    )
    parser.add_argument(
        "--list-models",
        "-l",
        action="store_true",
        dest="list_models",
        help="利用可能な LLM モデル一覧を表示します",
    )
    parser.add_argument(
        "--generate-commit-msg",
        "-g",
        action="store_true",
        dest="generate_commit_msg",
        help="コミットメッセージ出力",
    )
    parser.add_argument(
        "--review",
        "-r",
        action="store_true",
        help="指定ファイルまたは Git 差分のコードレビューを実行します",
    )
    return parser


def _build_main_execution_parser(
    global_parser: argparse.ArgumentParser,
) -> argparse.ArgumentParser:
    """メイン対話・ワンショット実行用オプションを定義."""
    parser = argparse.ArgumentParser(
        description="LLM / RAG / MCP / Context Caching を統合した CLI ツール",
        parents=[global_parser],
    )
    parser.add_argument(
        "--rag",
        action="store_true",
        help="RAG (ChromaDB Vector Store) 検索によるコンテキスト注入を有効化",
    )
    parser.add_argument(
        "--mcp",
        action="store_true",
        help="MCP サーバーとの連携を有効化",
    )
    parser.add_argument(
        "-c",
        "--cache",
        nargs="?",
        const=True,
        default=False,
        help="Context Caching を利用。指定なしで最新キャッシュ自動選択, Cache ID 指定で特定キャッシュ再利用",
    )
    parser.add_argument(
        "-f",
        "--file",
        type=str,
        action="append",
        dest="files",
        help="コンテキストとしてロードする（または書き込み対象とする）ファイル・ディレクトリパス",
    )
    parser.add_argument(
        "-m",
        "--model",
        type=str,
        default="gemini-3.5-flash",
        help="使用する LLM モデル名 (デフォルト: gemini-3.5-flash)",
    )
    parser.add_argument(
        "-p",
        "--provider",
        type=str,
        default="gemini",
        help="使用する LLM プロバイダ (デフォルト: gemini)",
    )
    parser.add_argument(
        "-w",
        "--write",
        action="store_true",
        dest="write_mode",
        help="生成・修正結果を対象ファイルに直接書き込み・適用",
    )
    parser.add_argument(
        "-a",
        "--auto-save",
        action="store_true",
        dest="auto_save",
        help="対話ログや出力結果を自動保存",
    )
    return parser


def _read_stdin_content() -> str:
    """標準入力 (パイプやリダイレクト) からテキストを読み込む.

    Returns:
        標準入力から読み込まれたテキスト. 端末（tty）からの入力である場合は空文字列.

    """
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return ""
