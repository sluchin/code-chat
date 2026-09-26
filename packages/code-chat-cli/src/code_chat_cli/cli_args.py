"""Code Chat CLI - 引数パーサーおよびコンテキストコレクター.

このモジュールは, Code Chat CLI アプリケーションのためにコマンドライン引数を解析し,
ファイルまたは標準入力からコンテキストを収集します.
"""

from dataclasses import dataclass, field


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

    log_level: str = "INFO"
    """ログレベル文字列."""

    trace_mode: bool = False
    """サードパーティ製ライブラリのトランスポートログ制御."""

    dry_run: bool = False
    """ドライラン（実行処理の事前検証・試行）フラグ."""

    list_models: bool = False
    """モデル一覧表示フラグ."""

    login: bool = False
    """`--login` による Gemini API への OAuth ログインフラグ."""

    oauth: bool = False
    """`--oauth` による認証方法の指定 (API キーではなく OAuth を使う)."""

    generate_commit_msg: bool = False
    """コミットメッセージ生成フラグ."""

    review: bool = False
    """`--review` によるコードレビュー・静的解析モードフラグ."""

    staged: bool = False
    """`--staged` によるレビュー対象をステージング済み差分に限定するフラグ."""

    # rag サブコマンド固有フラグ
    input_dirs: list[str] = field(default_factory=list)
    """インデックス作成対象のディレクトリパス"""

    output_dir: str | None = "./.chroma_db"
    """インデックス出力ディレクトリパス"""
