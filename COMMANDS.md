# Code Chat CLI コマンド仕様書

`code-chat` は、マルチプロバイダ対応、RAG (コードベース検索)、MCP (ツール連携)、Context Caching (Gemini) を統合した開発者向け CLI ツールです。

---

## 1. 基本設計指針 (Prompt-First & Subcommand-Management)

* **デフォルト実行 (`code-chat`)**: メイン対話・質問機能
* プロンプト引数 (`prompt`) あり $\rightarrow$ ワンショット実行 (処理結果を出力して終了)
* プロンプト引数 (`prompt`) なし $\rightarrow$ 対話モード (REPL) 起動

* **サブコマンド (`rag`, `cache`, `mcp`)**: 各リソースの管理・個別実行系コマンド

---

## 2. メイン対話・質問機能 (デフォルト動作)

サブコマンドなしで起動することで、対話モードまたはワンショット実行を行います。フラグを指定することで、RAG、MCP、Context Caching を動的に有効化・併用可能です。

### 構文

```bash
code-chat [PROMPT] [OPTIONS]

```

### オプション一覧

| オプション | 型 | デフォルト値 | 説明 |
| --- | --- | --- | --- |
| `PROMPT` | 位置引数 (文字列) | `None` | 実行するプロンプト。省略時は対話モード (REPL) を起動 |
| `--rag` | フラグ | `False` | RAG (ChromaDB Vector Store) 検索によるコンテキスト注入を有効化 |
| `--mcp-local` | フラグ | `False` | ローカル MCP サーバー（ファイル操作・CLI実行等）との連携を有効化 |
| `--mcp-github` | フラグ | `False` | 外部 GitHub MCP サーバー（PR/Issue/Commit操作等）との連携を有効化 |
| `-c, --cache` | フラグ / 文字列 | `False` | Context Caching を利用。指定なしで最新キャッシュ自動選択、Cache ID 指定で特定キャッシュ再利用 |
| `-f, --file <PATH>` | 文字列 (複数指定可) | なし | 追加コンテキストとしてロードする（または書き込み対象とする）ファイル・ディレクトリパス |
| `-m, --model` | 文字列 | `gemini-2.5-flash` | 使用する LLM モデル名 |
| `-p, --provider` | 文字列 | `gemini` | LLM プロバイダ (`gemini`, `claude`, `openai`, `local`) |
| `-w, --write` | フラグ | `False` | 生成・修正結果を対象ファイルに直接書き込み・適用 |
| `-a, --auto-save` | フラグ | `False` | 対話ログや出力結果を自動保存 |
| `-g, --generate-commit-msg` | フラグ | `False` | Staged な Git 差分からコミットメッセージを自動生成 |
| `-r, --review` | フラグ | `False` | 指定ファイルまたは Git 差分のコードレビューを実行 |
| `-l, --list-models` | フラグ | `False` | 利用可能な LLM モデルの一覧を表示 |
| `--trace` | フラグ | `False` | ライブラリ内部通信ログを出力 |
| `--trace` | フラグ | `False` | SDK や HTTP クライアント等のライブラリ内部通信ログを出力 |
| `-D, --debug` | フラグ | `False` | デバッグログを出力 |
| `--dry-run` | フラグ | `False` | API 呼び出しを行わず、読み込まれるファイル群や指定引数の確認のみ実行 |

### 実行例

```bash
# 通常の対話モード起動
code-chat

# ワンショット実行
code-chat "このコードのバグを修正して" -f ./src/main.py

# RAG 検索を組み合わせてワンショット実行
code-chat "認証機能の実装箇所を抽出して説明して" --rag

# RAG, MCP(GitHub/Local), Context Caching をすべて有効化して対話
code-chat "Issue #42に基づきローカルコードを修正してPRを作成して" --rag --mcp-local --mcp-github --cache

# 特定の Cache ID を明示指定して対話モード起動
code-chat --cache cachedContents/abc123xyz456

# Git の変更差分からコミットメッセージを自動生成
code-chat --generate-commit-msg

# 指定ファイルのコードレビューを実行
code-chat --review -f ./src/main.py

# プロバイダで利用可能なモデル一覧を取得
code-chat --list-models -p gemini

```

---

## 3. 管理用サブコマンド仕様

### 3.1 `rag` (RAG インデックス管理)

Vector DB (`.chroma_db`) の作成、差分更新、削除、ステータス確認を行います。

| コマンド | 引数 | 説明 |
| --- | --- | --- |
| `code-chat rag create` | `[PATH]` | 指定パス（省略時は `./`）のコードベースを走査して Vector DB を作成 |
| `code-chat rag update` | `[PATH]` | 指定パス（省略時は `./`）の差分インデックスを更新 |
| `code-chat rag rm` | なし | 構築済みの Vector DB (`.chroma_db`) を削除 |
| `code-chat rag status` | なし | 現在登録されているドキュメントチャンク数や DB ステータスを表示 |

#### 実行例

```bash
# カレントディレクトリのインデックス作成
code-chat rag create

# 特定ディレクトリの差分更新
code-chat rag update ./src

# Dry-run によるインデックス対象ファイルの確認
code-chat rag create ./src --dry-run

# DB ステータスの確認
code-chat rag status

# インデックスの削除
code-chat rag rm

```

---

### 3.2 `cache` (Context Caching 管理)

Gemini サーバー上のキャッシュ (Context Caching) のライフサイクル管理を行います。

| コマンド | 引数 / オプション | 説明 |
| --- | --- | --- |
| `code-chat cache create` | `[PATH]` `--ttl <SECONDS>` | 指定パスのコンテキストを読み込んで新規キャッシュを作成 (デフォルト TTL: 3600秒) |
| `code-chat cache update` | `[PATH]` | 既存のキャッシュを更新・再作成 |
| `code-chat cache rm` | `[CACHE_ID]` | 指定したキャッシュ（省略時は全て）を削除・開放 |
| `code-chat cache list` | なし | 現在アクティブなキャッシュ一覧を表示 |

#### 実行例

```bash
# 指定ディレクトリから新規キャッシュを作成 (保持時間 2時間)
code-chat cache create ./src --ttl 7200

# キャッシュを最新コードで更新
code-chat cache update ./src

# 現在有効なキャッシュ一覧を表示
code-chat cache list

# キャッシュの削除
code-chat cache rm cachedContents/abc123xyz456

```

---

### 3.3 `mcp` (MCP サーバー管理・実行)

Model Context Protocol (MCP) サーバーの起動、ステータス確認、動作テストを行います。

| コマンド | 引数 | 説明 |
| --- | --- | --- |
| `code-chat mcp run` | `<SERVER_NAME>` | 指定した MCP サーバーを個別起動 |
| `code-chat mcp status` | なし | 登録されている MCP サーバーの接続状態・一覧を表示 |
| `code-chat mcp test` | `[SERVER_NAME]` | 指定（または全）MCP サーバーの導通テストを実行 |

#### 実行例

```bash
# 特定の MCP サーバーを起動
code-chat mcp run github

# MCP サーバーの接続状態確認
code-chat mcp status

# 全 MCP サーバーの導通テスト
code-chat mcp test

```
