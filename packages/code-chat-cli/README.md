# code-chat-cli

`code-chat-cli` は, Gemini を使った対話・コード修正・コードレビュー・コミットメッセージ生成に, RAG (コードベース検索) と MCP (ツール連携) を組み合わせた CLI ツール `code-chat` の本体です.

コマンドとオプションの一覧は, リポジトリのルートの [COMMANDS.md](../../COMMANDS.md), セットアップと使い方は [README.md](../../README.md) を参照してください.

---

## 主な機能

* **対話・ワンショット実行**: ファイル (`-f`) や標準入力をコンテキストにして, Gemini と対話します. プロンプトを引数で渡すとワンショット, 省略すると対話モード (REPL) です.
* **Write モード (`-w`)**: 生成したコードを対象ファイルへ反映します. 確認, 省略コードの検知, 世代付きのバックアップがあります.
* **コードレビュー (`-r`)**, **コミットメッセージ生成 (`-g`)**, **モデル一覧 (`-l`)**.
* **RAG (`--rag`, `rag` サブコマンド)**: `code-chat-rag` で検索したコードを, 質問に付加します.
* **MCP (`--mcp`, `mcp` サブコマンド)**: `code-chat-mcp` の MCP サーバーのツールを, Gemini の Function Calling で呼び出します.
* **Context Caching (`-c`, `cache` サブコマンド)**: 大きなコンテキストを Gemini のサーバー上にキャッシュして, 再利用します.
* **認証**: API キー (`GEMINI_API_KEY`) と, OAuth (`--login`, `--oauth`) に対応します.

チャットは, すべて, サブコマンドなしで, `--rag`, `--mcp`, `-c` などを指定して行います. `rag` / `cache` / `mcp` のサブコマンドは, 管理用です (`rag create`, `cache list`, `mcp status` など).

---

## インストール

リポジトリのルートで, `uv` を使って依存関係をセットアップします.

```bash
uv sync
```

`code-chat` と `cchat` の 2 つのコマンドは, どちらも `code_chat_cli.chat:main` を実行します. 開発環境では `uv run code-chat` で実行できます.

---

## 使い方 (抜粋)

```bash
# 対話モード
uv run code-chat

# ワンショット実行 (ファイルをコンテキストにする)
uv run code-chat "このコードのバグを修正して" -f ./src/main.py

# RAG で検索したコードを付加して質問する (事前に rag create が必要)
uv run code-chat rag create
uv run code-chat "認証機能の実装箇所を説明して" --rag

# MCP のツールを使って実行する
uv run code-chat "git の状態を確認して" --mcp
```

---

## 主なモジュール

| モジュール | 役割 |
| --- | --- |
| `chat.py` | エントリポイント (`main`), 対話・ワンショットの処理, サブコマンドの振り分け |
| `args.py` / `cli_args.py` | 引数の解析, 解析結果を保持するデータクラス (`CliArgs`) |
| `client.py` / `auth.py` | Gemini クライアントの作成, API キーと OAuth の認証 |
| `context_cache.py` | Context Caching の作成・更新・削除・一覧・解決 |
| `file_writer.py` / `file_utils.py` | Write モードのファイル書き込みとバックアップ, パスからのコンテキストの読み込み |
| `commands/` | コードレビュー (`review.py`), コミットメッセージ生成 (`commit.py`), モデル一覧 (`models.py`) |
| `rag.py` | `rag` サブコマンドのハンドラー (`code-chat-rag` を呼び出す) |
| `mcp.py` / `query_handler.py` | MCP の実行 (`handle_mcp_run`) と, Gemini と MCP サーバーの間のツール呼び出しのループ (`QueryHandler`) |
| `prompts.py` | システム指示とプロンプトテンプレート |

ロガー, Gemini API のリトライ, エラーの概要・ヒントの作成は, 共通ライブラリ `code-chat-lib` にあります.

---

## 開発・テスト

リポジトリのルートで実行します.

```bash
# このパッケージのテストだけを実行する
uv run pytest --no-cov tests/code_chat_cli

# 全テストとカバレッジの確認 (100% が合格基準)
uv run pytest
```
