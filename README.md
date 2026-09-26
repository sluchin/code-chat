# code-chat

Gemini API を使用してローカルソースコードの参照・対話・自動更新を行う CLI ツール。

## 主な機能 (Features)

`code-chat` は、ローカルのソースコード構造を理解し、CLI 上で直接コードの参照・修正・レビュー・コミット作成までを完結させるための開発者向け AI ツールです。

- 💬 **ローカルコードベースとの対話 (Interactive Chat)**
  - ファイルやディレクトリ (`-f`)、標準入力（パイプ）をコンテキストとして読み込み、コードの解説やバグ修正案を確認できます。
  - プロンプトを引数で渡すとワンショット実行、省略すると対話モード (REPL) で起動します。

- ✏️ **ファイルへの直接書き込み・自動更新 (`-w`, `--write`)**
  - LLM が生成したコードを対象ファイルへ反映します。
  - **安全設計**: 実行前の確認プロンプト、省略コード（`# ...` や「変更なし」など）の検知による警告、上書き前のバックアップ（`.bak.orig` と直近 5 世代のタイムスタンプ付きバックアップ）。

- 🔎 **コードレビュー (`-r`, `--review`)**
  - 指定ファイル (`-f`) または Git の差分（`--staged` でステージ済み差分）を LLM がレビューします。

- 📝 **Git コミットメッセージの自動生成 (`-g`, `--generate-commit-msg`)**
  - `git diff` の変更内容を分析し、Conventional Commits 形式のコミットメッセージを生成します。

- 📚 **RAG (コードベース検索) (`--rag`, `rag` サブコマンド)**
  - ソースコードをチャンク分割して ChromaDB にインデックス化し、質問に関連するコードを検索して回答のコンテキストに加えます。

- 🔌 **MCP (Model Context Protocol) 統合 (`--mcp`, `mcp` サブコマンド)**
  - 外部の MCP サーバーのツールを Gemini の Function Calling 経由で呼び出します。

- 🗃️ **Context Caching (`-c`, `--cache`, `cache` サブコマンド)**
  - 大きなコンテキスト (ソースコード一式など) を Gemini サーバー上にキャッシュし、繰り返しの質問で再利用します (明示的キャッシュ)。
  - 明示的キャッシュは **有料枠 (課金が有効なプロジェクト) の API キーでのみ**利用できます。無料枠と `--oauth` では利用できません。
  - キャッシュを指定しなくても、同じ内容を先頭に送り続けると Gemini が自動でキャッシュします (暗黙のキャッシュ)。ヒットしたトークン数は、応答後に `キャッシュヒット: 12264 / 16718 トークン (73%)` のようにログへ出力されます。

- 🛡️ **開発基盤**
  - `ruff` / `pylint` / `mypy` / `pytest` / `pre-commit` によるチェック。

> **未実装**: `-p/--provider` は現時点では `gemini` のみ対応です。

コマンドとオプションの一覧は [COMMANDS.md](COMMANDS.md) も参照してください。

## Gemini CLI との違い (code-chat を使うメリット)

Google 公式の [Gemini CLI](https://github.com/google-gemini/gemini-cli) は、ファイル編集・シェル実行・Web 検索などを自律的に行うエージェントです。汎用の用途や、無料枠の広さでは Gemini CLI が有利です。

- 無料枠: Gemini CLI は「Google アカウントでログイン」すると、1 日 1,000 リクエスト (無料の API キーは 1 日 250 リクエスト、Flash 系のモデルのみ)。数字は公式のドキュメントによるもので、変更される場合があります。
- code-chat の `--oauth` は Gemini API に直接アクセスするため、**無料枠は API キーと同じ**です (Gemini CLI のログインの枠は使えません)。

code-chat を使うメリットは、次のとおりです。

- **RAG (ChromaDB)**: リポジトリを自前でインデックス化し、検索結果を質問に付加します。`--rag` と `--mcp` は併用できます。
- **明示的な Context Caching**: `cache create` で作成し、`-c` で再利用します (有料枠が必要)。
- **エラー表示とリトライの制御**: 429 / 503 を、原因とヒントを付けた 1 行で表示します。`retryDelay` に従って自動でリトライし、1 日の上限は対象から除きます (RAG を含む全ての Gemini 呼び出しで統一)。詳しくは [ERRORS.md](ERRORS.md) を参照してください。
- **非対話での利用**: パイプ入力、`--review`、`-g` (コミットメッセージ生成) を、ワンショットで実行できます。
- **Write モードの安全性**: 上書き前に確認し、省略コードを検知して警告し、世代付きのバックアップを残します。
- **変更しやすい**: プロンプト、リトライの方針、MCP の扱いを、自分で決められます。

使い分けの目安: 無料で広く使いたい場合や、エージェントとして自律的に作業させたい場合は Gemini CLI、RAG・Context Caching・エラーとリトライの細かい制御・独自のワークフローが必要な場合は code-chat を使います。

## プロジェクト構成

uv workspace による 4 パッケージ構成です。

| パッケージ | 役割 |
| --- | --- |
| `packages/code-chat-cli` | CLI 本体 (`code_chat_cli`): 引数解析、対話、ファイル書き込み、レビュー、コミットメッセージ生成 |
| `packages/code-chat-lib` | 共通ライブラリ (`code_chat_lib`): ロガー、Gemini API のリトライ、エラーの概要・ヒントの作成。他のパッケージに依存しない |
| `packages/code-chat-rag` | RAG (`code_chat_rag`): インデックス作成、ベクトルストア (ChromaDB)、検索 |
| `packages/code-chat-mcp` | MCP (`code_chat_mcp`): 設定読み込み、MCP サーバーの起動とツール呼び出し |

## 前提条件

- **Python**: 3.12 以上
- **uv**: パッケージ管理ツール ([インストール方法](https://docs.astral.sh/uv/))
- **Git**: コミットメッセージ生成・差分レビューで使用
- **Node.js**: `npx` (MCP サーバーを `npx` で起動する場合)
- **Gemini API キー**

## セットアップ・インストール手順

### 1. 開発環境のセットアップ

```bash
# 1. リポジトリの clone と移動
git clone <repository-url>
cd code-chat

# 2. 仮想環境の作成と依存ライブラリの同期 (uv.lock に基づいて自動インストール)
uv sync

# 3. pre-commit フックの有効化 (コミット時の自動コードチェック)
uv run pre-commit install
```

### 2. CLI ツールとしてのインストール

`uv tool` を使用すると、環境を汚さずに CLI コマンドとしてグローバルにインストールできます。

```bash
# ローカルリポジトリから CLI ツールとしてインストール
uv tool install .

# インストール後は直接コマンドとして呼び出し可能
code-chat
```

> **Note:** 開発中の変更を即座に反映させたい場合は、編集可能モード（Editable install）でインストールします。
> ```bash
> uv tool install --editable .
> ```

> **Note:** `cchat` という短縮コマンドは `packages/code-chat-cli` パッケージに定義されています。開発環境では `uv run cchat` で利用できますが、`uv tool install .` ではインストールされません。

### 3. (任意) Claude Code を使う場合のローカル設定

[Claude Code](https://claude.com/claude-code) でこのリポジトリを開発する場合、`uv` コマンド (`uv run pytest` など) を確認なしで実行できるようにするには、`.claude/settings.local.json` を作成して次の内容を書きます。

```json
{"permissions": {"allow": ["Bash(uv *)"]}}
```

> **Note:** `.claude/` は `.gitignore` の対象です (コミットされません)。`Bash(uv *)` は `uv run python -c ...` のような任意のコードを実行するコマンドも許可するため、個人のローカル環境でのみ設定してください。

## 認証の設定

Gemini API への認証は、次のいずれかを選びます。**既定は API キー**で、OAuth を使うときは `--oauth` オプションを指定します。`GEMINI_API_KEY` が設定されていても、`--oauth` を付ければ OAuth が使われます。

### 方法 1: API キー

Gemini API キーを環境変数 `GEMINI_API_KEY` に設定してください。

```bash
export GEMINI_API_KEY=your_api_key_here
```

### 方法 2: OAuth ログイン (Google アカウント)

ブラウザで Google アカウントにログインして認証します。API キーは不要です。Google Cloud での設定を含む詳しい手順は、[OAUTH.md](OAUTH.md) を参照してください。以下は概要です。

1. Google Cloud コンソールで、Gemini API を使うプロジェクトに **OAuth クライアント ID** (種類: **デスクトップアプリ**) を作成します。
2. OAuth 同意画面が「テスト中」の場合は、ログインに使う Google アカウントを **テストユーザー** に追加します (追加しないと `access_denied` になります)。
3. クライアント ID とシークレットを環境変数に設定します (`~/.zshenv` などに書いておくと、毎回設定せずに済みます)。

   ```bash
   export GEMINI_OAUTH_CLIENT_ID=your-client-id.apps.googleusercontent.com
   export GEMINI_OAUTH_CLIENT_SECRET=your-client-secret
   ```

4. ログインします。

   ```bash
   code-chat --login
   ```

5. `--oauth` を付けて実行します。

   ```bash
   code-chat --oauth "こんにちは"
   ```

トークンは `~/.config/code-chat/oauth_token.json` (所有者のみ読み書き可能) に保存され、期限切れ時は自動で更新されます。

- **`--oauth` を付けたときだけ OAuth を使います。** 付けない場合は、`GEMINI_API_KEY` の API キーを使います (未設定ならエラーです。OAuth に自動では切り替わりません)。
- `--oauth` を付けて、保存済みのトークンがない場合、対話端末から起動すると自動でブラウザ認証が始まります。パイプ実行などの非対話環境では、`code-chat --login` の実行を促すエラーで終了します。
- 毎回 `--oauth` を付けたくない場合は、`alias code-chat='code-chat --oauth'` のようにエイリアスを設定してください。
- ダウンロードした OAuth クライアントの JSON (`client_secret_*.json`) は `.gitignore` の対象です。リポジトリに含めないでください。
- OAuth 同意画面が「テスト中」のままだと、リフレッシュトークンは 7 日で失効し、再ログインが必要になります。
- **`--oauth` にしても、無料枠は API キーと同じで、増えません。** 上限は、OAuth クライアントを作成したプロジェクトの Gemini API の無料枠です (確認: `gemini-3.5-flash` は、どちらも 1 分あたり 5 リクエスト)。詳しくは [OAUTH.md](OAUTH.md#9-制限事項) を参照してください。
- RAG (`--rag`, `rag` サブコマンド) は Embedding API を langchain 経由で呼び出すため、OAuth に対応していません。`--rag` と `--oauth` を併用する場合、RAG の検索には `GEMINI_API_KEY` の API キーが使われます (Gemini への問い合わせ自体は OAuth です)。

> **Note:** `.env` ファイルは自動では読み込まれません。`.env` を使う場合は `uv run --env-file .env code-chat ...` のように明示するか、シェルで読み込んでください。

## 使い方

`uv run` 経由、またはインストール済みの `code-chat` コマンドで実行します。

```bash
# 対話モードで起動 (終了: exit / quit / q、会話ログ保存: /save <path>)
code-chat

# ワンショット実行 (ファイルをコンテキストにして質問)
code-chat "このコードのバグを修正して" -f ./src/main.py

# パイプ入力をコンテキストにする
git diff | code-chat "この変更を要約して"

# 対象ファイルを LLM の出力で更新 (確認プロンプトあり)
code-chat "型ヒントを追加して" -f ./src/main.py --write

# コードレビュー (ファイル指定 / Git 差分 / ステージ済み差分)
code-chat --review -f ./src/main.py
code-chat --review
code-chat --review --staged

# Git 差分からコミットメッセージを生成
code-chat --generate-commit-msg

# 利用可能なモデル一覧
code-chat --list-models

# Context Caching: コンテキストをキャッシュして再利用 (有料枠の API キーが必要)
code-chat cache create ./src
code-chat -c "認証まわりの実装を説明して"
code-chat cache list
code-chat cache rm

# Google アカウントで OAuth ログイン (初回のみ)
code-chat --login

# OAuth で実行 (GEMINI_API_KEY が設定されていても OAuth を使う)
code-chat --oauth "こんにちは"

# API を呼ばずに解析結果だけ確認
code-chat "テスト" -f ./src/main.py --dry-run
```

主なオプション:

| オプション | 説明 |
| --- | --- |
| `[PROMPT]` | プロンプト。省略時は対話モード |
| `-f, --file <PATH>` | コンテキストとして読み込む（`-w` の書き込み対象にもなる）ファイル・ディレクトリ。複数指定可。`--rag` / `--mcp` とは併用できません (エラー終了) |
| `-m, --model <MODEL>` | 使用するモデル (デフォルト: `gemini-3.5-flash`) |
| `-w, --write` | 生成コードを対象ファイルに書き込む |
| `-r, --review` / `--staged` | コードレビュー / ステージ済み差分のみ対象 |
| `-g, --generate-commit-msg` | コミットメッセージを生成 |
| `-l, --list-models` | モデル一覧を表示 |
| `--login` | ブラウザで OAuth ログインし、トークンを保存して終了 |
| `--oauth` | `GEMINI_API_KEY` ではなく OAuth (`--login` で保存したトークン) で認証 |
| `-c, --cache` | キャッシュを使用 (`-c` で最新、`--cache=<ID>` で指定)。`-w` / `--oauth` とは併用不可 (エラー終了)。`--mcp` とは引数のエラーにはしませんが、ツール定義をキャッシュに含められないため、Gemini API が 400 を返す想定です |
| `--rag` | RAG 検索によるコンテキスト注入 (`--mcp` と併用可) |
| `--mcp` | MCP ツール連携 (`--rag` と併用可) |
| `--max-tool-rounds N` | `--mcp` 時のツール呼び出しの回数の上限 (既定: 20)。超えるとエラー終了します |
| `-a, --auto-save` | 対話ログを `<日時>_chat.md` に自動保存 |
| `-D, --debug` / `--log-level` / `--trace` | ログ出力の制御 (`--trace` は、ライブラリの通信ログと、Gemini API エラー時のトレースバックも出力) |
| `--dry-run` | API 呼び出しを行わず引数と読み込み内容を表示 |

## RAG (コードベース検索)

Vector DB は既定で `./.chroma_db` に作成されます。インデックス作成と検索には Gemini の Embedding API を使用します。

```bash
# インデックスの作成 (既存の内容は初期化されます)
code-chat rag create --input_dirs ./packages --output_dir ./.chroma_db

# 差分更新 (読み込んだファイルの既存のチャンクを置き換えます)
code-chat rag update --input_dirs ./packages

# ステータス確認 / 削除
code-chat rag status
code-chat rag rm

# RAG を有効にして質問
code-chat "認証機能の実装箇所を説明して" --rag
```

> **Note:** `-f` (ファイルをそのまま送信) は `--rag` / `--mcp` と併用できません。併用するとエラー終了します。`--rag --mcp` を併用すると、RAG で検索したコンテキストが MCP に渡すプロンプトに付加されます。

> **Note:** `--dry-run` は API 呼び出しを伴う処理全般をスキップする共通オプションです。`rag create --dry-run` / `rag update --dry-run` では、引数の解析結果に続けて、インデックス対象ファイルの一覧を表示します。

インデックス対象の拡張子は `.py` `.cpp` `.hpp` `.c` `.h` `.ts` `.js` で、`.git` `.venv` `node_modules` などの除外ディレクトリと、`.` で始まる隠しディレクトリはスキップされます。

## MCP (Model Context Protocol) の設定と利用

`code-chat` は MCP に対応しており、Gemini が MCP サーバーのツールを呼び出して回答できます。

### 1. 設定ファイル

設定ファイルは `~/.config/code-chat/mcp.json` から読み込まれます（ファイルが無い場合は警告が出て、サーバーなしで動作します）。

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "${CWD}"
      ],
      "enabled": true
    },
    "commands": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-server-commands",
        "--allowed-commands",
        "uv,git"
      ],
      "enabled": true
    }
  }
}
```

- `args` 内の `${CWD}` は、実行時のカレントディレクトリの絶対パスに置換されます。
- `env`（環境変数の辞書）は任意です。`"enabled": false` でサーバーを無効化できます。
- ツール名は `<サーバー名>__<ツール名>` の形式で Gemini に渡されます。
- Gemini がツールを呼び続けて終わらなくなることを防ぐため、ツール呼び出しの繰り返しは、既定で 20 回までです (`--max-tool-rounds N` で変更できます。超えるとエラー終了します)。
- ワンショット実行 (`code-chat "..." --mcp`) が失敗した場合は、終了コード 1 で終了します。

> **重要:** `mcp-server-commands` の許可コマンドは必要最小限（例: `uv`, `git`）に絞り、実行時も `uv run pytest` のように `uv run` を前置する運用を推奨します。

### 2. 実行

```bash
# MCP サーバーの一覧とツールを表示
code-chat mcp status

# 全 MCP サーバーの導通テスト (サーバーごとに [OK] / [NG] を表示)
code-chat mcp test

# MCP を使ってワンショット実行
code-chat "git の状態を確認して" --mcp

# RAG で検索したコードをプロンプトに付加して、MCP のツールを使って実行
code-chat "認証機能の実装箇所を調べて、関連する変更履歴を確認して" --rag --mcp

# 対話モード内では /mcp を前置して実行
# You > /mcp 未コミットの変更を要約して
```

詳細は [packages/code-chat-mcp/README.md](packages/code-chat-mcp/README.md) を参照してください。

## ビルド

```bash
uv build
```

## テストの実行

`pytest` を使用してテストおよびカバレッジ測定を実行します（設定は `pyproject.toml` の `[tool.pytest.ini_options]`）。テストは `tests/code_chat_cli/`、`tests/code_chat_lib/`、`tests/code_chat_rag/`、`tests/code_chat_mcp/` にあります。

```bash
# 全テストの実行とカバレッジの確認
uv run pytest

# 特定のテストファイル全体を実行
uv run pytest --no-cov tests/code_chat_cli/test_args.py -vv --tb=short

# 特定のテスト関数を実行
uv run pytest --no-cov tests/code_chat_cli/test_args.py::TestParseArgs::test_parse_args_default_success -vv --tb=short

# テスト名のキーワード指定 (名前に "retry" を含むテストのみ)
uv run pytest --no-cov -k "retry" -vv --tb=short

# 標準出力をキャプチャせずに表示
uv run pytest --no-cov tests/code_chat_cli/test_chat.py -s -vv --tb=short
```

> **Note:** カバレッジは 100% を基準（`fail_under = 100`）としており、下回ると `uv run pytest` は失敗します。一部のテストだけを実行する場合は、基準の判定を避けるため `--no-cov` を付けてください（例: `uv run pytest --no-cov tests/code_chat_cli/test_args.py`）。

## コード品質チェック・開発用コマンド

```bash
# リンター・フォーマッター (Ruff)
uv run ruff check --fix .
uv run ruff format .

# 詳細リンターチェック (Pylint)
uv run pylint packages tests

# pre-commit フックの手動実行 (全ファイル対象: trailing-whitespace / ruff / pylint / mypy)
uv run pre-commit run --all-files

# pre-commit フックの更新
uv run pre-commit autoupdate
```

> **Note:** 型チェック (Mypy) は `uv run pre-commit run mypy --all-files` で実行してください。

## トラブルシューティング

Gemini API のエラー (429、503、404 など) の原因と対処、`code-chat` のリトライ動作は、[ERRORS.md](ERRORS.md) にまとめています。

### `uv run pytest` 実行時に `unrecognized arguments: --cov=...` エラーが発生する

`pytest-cov` などの開発用依存パッケージが仮想環境（`.venv`）内にインストールされていない可能性があります。
以下の手順で開発用依存関係を含めて再同期してください。

```bash
# 開発用依存関係を含めて同期
uv sync --dev
```

上記で解消しない場合や、パッケージ名の変更・環境構築時の不整合が発生している場合は、仮想環境を一度再構築・再同期してください。

```bash
# 仮想環境をクリアして全依存関係を再同期
uv sync --all-groups --reinstall
```

### `GEMINI_API_KEY is missing` と表示される

環境変数 `GEMINI_API_KEY` が設定されていません。`.env` は自動で読み込まれないため、`export` するか `uv run --env-file .env ...` を使用してください。API キーの代わりに OAuth を使う場合は、[OAuth ログイン](#方法-2-oauth-ログイン-google-アカウント)を行い、`--oauth` を指定してください。

### `OAuth credentials are missing` と表示される

`--oauth` を指定しましたが、OAuth の設定または保存済みのトークンがありません。表示されたメッセージに従って、環境変数の設定と `code-chat --login` を行ってください。

### OAuth ログインで `access_denied` (エラー 403) になる

OAuth 同意画面が「テスト中」で、ログインしたアカウントがテストユーザーに登録されていません。Google Cloud コンソールの「Google Auth Platform」→「対象」で、テストユーザーに追加してください。

### OAuth の再ログインを求められる

リフレッシュトークンが失効しています (同意画面が「テスト中」の場合は 7 日で失効します)。`code-chat --login` で再ログインしてください。
