"""Code Chat CLI - 引数パーサーおよびコンテキストコレクター.

このモジュールは, Code Chat CLI アプリケーションのためにコマンドライン引数を解析し,
ファイルまたは標準入力からコンテキストを収集します."""

import argparse
import sys

from code_chat_cli.cli_args import CliArgs
from code_chat_cli.file_utils import read_path_content
from code_chat_cli.logger import get_logger

logger = get_logger(__name__)
_SUBCOMMANDS = ("rag", "cache", "mcp")
_VALUE_OPTIONS = {"-f", "--file", "-m", "--model", "-p", "--provider", "--log-level"}


# pylint: disable=too-many-locals,too-many-statements
def parse_args(args: list[str] | None = None) -> CliArgs:
    """コマンドライン引数を解析し, コンテキストを取得して返す.

    Args:
        args (list[str] | None, optional): 解析対象の引数リスト. Defaults to None.

    Returns:
        CliArgs: 解析された引数とコンテキスト情報を保持するオブジェクト.

    """
    if args is None:
        args = sys.argv[1:]

    # 先頭の位置引数がサブコマンドでなければ, 位置引数はすべてプロンプトとして扱う
    # (argparse のサブコマンド解決が "invalid choice" で失敗するのを避ける)
    args, prompt_tokens = _split_prompt_tokens(args)

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
        "--input_dirs",
        nargs="+",
        type=str,
        default=["."],
        help="入力パス (デフォルト: .)",
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
        "--input_dirs",
        nargs="+",
        type=str,
        default=["."],
        help="入力パス (デフォルト: .)",
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

    #    mcp_run = mcp_subparsers.add_parser(
    #        "run", parents=[global_parser], help="指定した MCP サーバーを個別起動"
    #    )
    #    mcp_run.add_argument("target", help="サーバー名")

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
        prompt_str = " ".join([*prompt_tokens, *unparsed_args])

    # -f はファイル内容をそのまま送信する用途のため, RAG / MCP とは併用できない
    if raw_args.files and (raw_args.rag or raw_args.mcp):
        main_parser.error("-f/--file は --rag / --mcp と併用できません")

    # Context Caching は, Write モード (システム指示が異なる) と併用できない.
    # --mcp との併用 (ツール定義がキャッシュに含まれない) は, ここでは止めず, Gemini API のエラーに任せる
    if raw_args.cache and raw_args.write_mode:
        main_parser.error("-c/--cache は -w/--write と併用できません")

    # Context Caching は API キーでのみ利用できる (OAuth のスコープが対応していない)
    if raw_args.oauth and (raw_args.cache or raw_args.subcommand == "cache"):
        main_parser.error(
            "Context Caching (-c/--cache, cache サブコマンド) は API キーのみ対応のため, "
            "--oauth と併用できません"
        )

    context_parts: list[str] = []

    # 標準入力の取得
    stdin_text = _read_stdin_content()
    if stdin_text:
        context_parts.append(f"--- [標準入力] ---\n{stdin_text}")

    # -f, --file オプションのテキスト読み込み
    file_targets: list[str] = raw_args.files or []

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
    debug_mode = raw_args.debug_mode
    log_level = raw_args.log_level
    if debug_mode or log_level == "DEBUG":
        debug_mode = True
        log_level = "DEBUG"

    # サブコマンドの前後どちらに指定しても有効にするため, 引数リストも直接確認する
    trace_mode = bool(raw_args.trace_mode or "--trace" in args)

    return CliArgs(
        subcommand=raw_args.subcommand,
        subcommand_action=getattr(raw_args, "subcommand_action", None),
        subcommand_target=getattr(raw_args, "target", None),
        prompt=prompt_str,
        files=file_targets,
        rag=raw_args.rag,
        mcp=raw_args.mcp,
        cache=raw_args.cache,
        model=raw_args.model,
        provider=raw_args.provider,
        write_mode=raw_args.write_mode,
        auto_save=raw_args.auto_save,
        context=context_str,
        cache_ttl=getattr(raw_args, "ttl", 3600),
        debug_mode=debug_mode,
        log_level=log_level,
        trace_mode=trace_mode,
        dryrun=raw_args.dryrun,
        list_models=raw_args.list_models,
        login=raw_args.login,
        oauth=raw_args.oauth,
        generate_commit_msg=raw_args.generate_commit_msg,
        review=raw_args.review,
        staged=raw_args.staged,
        input_dirs=input_dirs,
        output_dir=getattr(raw_args, "output_dir", "./.chroma_db"),
    )


def _split_prompt_tokens(args: list[str]) -> tuple[list[str], list[str]]:
    """サブコマンド未指定時に, オプション以外の位置引数をプロンプトとして分離する.

    Args:
        args (list[str]): コマンドライン引数リスト.

    Returns:
        tuple[list[str], list[str]]: (位置引数を除いた引数リスト, プロンプト用トークン).
            最初の位置引数がサブコマンドの場合は (args, []) を返す.

    """
    options: list[str] = []
    positionals: list[str] = []
    i = 0
    while i < len(args):
        token = args[i]
        # 単独の "-" は, オプションではなく, 位置引数として扱う
        if token.startswith("-") and token != "-":
            options.append(token)
            # 値を取るオプションの次の引数は, 位置引数ではなく, オプションの値として扱う
            if token in _VALUE_OPTIONS and i + 1 < len(args):
                i += 1
                options.append(args[i])
        else:
            if not positionals and token in _SUBCOMMANDS:
                return args, []
            positionals.append(token)
        i += 1
    return options, positionals


def _build_global_parser() -> argparse.ArgumentParser:
    """すべてのサブコマンドおよびメイン対話で共有される基本オプションを定義.

    Returns:
        argparse.ArgumentParser: グローバルオプションが定義されたパーサー.

    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument(
        "--dry-run",
        dest="dryrun",
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
        "--login",
        action="store_true",
        help="ブラウザで Google アカウントにログインし, Gemini API の OAuth トークンを保存します",
    )
    parser.add_argument(
        "--oauth",
        action="store_true",
        help="GEMINI_API_KEY ではなく OAuth (--login で保存したトークン) で認証します",
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
    parser.add_argument(
        "--staged",
        action="store_true",
        help="--review 時にステージング済み (--cached) の差分を対象にします",
    )
    return parser


def _build_main_execution_parser(
    global_parser: argparse.ArgumentParser,
) -> argparse.ArgumentParser:
    """メイン対話・ワンショット実行用オプションを定義.

    Args:
        global_parser (argparse.ArgumentParser): グローバル引数パーサー.

    Returns:
        argparse.ArgumentParser: メイン実行用オプションが追加されたパーサー.

    """
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
        help="Context Caching を利用。指定なしで最新キャッシュ自動選択, --cache=<Cache ID> の形式で特定キャッシュを再利用",
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
