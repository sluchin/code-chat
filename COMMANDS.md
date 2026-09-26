# Code Chat CLI コマンド仕様書

`code-chat` は、Gemini を使った対話・コード修正・コードレビュー・コミットメッセージ生成に、RAG (コードベース検索) と MCP (ツール連携) を組み合わせた開発者向け CLI ツールです。

> **実装状況**: `-p/--provider` の `gemini` 以外の値は、引数の定義のみで未実装です。該当箇所には「未実装」と記載しています。

---

## 1. 基本設計指針 (Prompt-First & Subcommand-Management)

* **デフォルト実行 (`code-chat`)**: メイン対話・質問機能
* プロンプト引数 (`PROMPT`) あり $\rightarrow$ ワンショット実行 (処理結果を出力して終了)
* プロンプト引数 (`PROMPT`) なし $\rightarrow$ 対話モード (REPL) 起動

* **サブコマンド (`rag`, `cache`, `mcp`)**: 各リソースの管理・個別実行系コマンド
* 最初の位置引数が `rag` / `cache` / `mcp` のときだけサブコマンドとして扱い、それ以外の位置引数はすべてプロンプトになります。

---

## 2. メイン対話・質問機能 (デフォルト動作)

サブコマンドなしで起動することで、対話モードまたはワンショット実行を行います。`--rag`、`--mcp` を指定することで、RAG や MCP を有効化できます。

### 構文

```bash
code-chat [PROMPT] [OPTIONS]

```

### オプション一覧

| オプション | 型 | デフォルト値 | 説明 |
| --- | --- | --- | --- |
| `PROMPT` | 位置引数 (文字列) | なし | 実行するプロンプト。省略時は対話モード (REPL) を起動 (複数語はスペースで結合) |
| `--rag` | フラグ | `False` | RAG (ChromaDB Vector Store) 検索によるコンテキスト注入を有効化。`--mcp` と併用すると、検索したコンテキストを MCP に渡すプロンプトに付加する。RAG の検索には API キー (`GEMINI_API_KEY`) が必要 (`--oauth` 指定時も) |
| `--mcp` | フラグ | `False` | MCP サーバーとの連携 (Function Calling によるツール実行) を有効化。`--rag` と併用可 |
| `--max-tool-rounds` | 整数 | `20` | `--mcp` 指定時に、Gemini のツール呼び出しを繰り返す回数の上限 (1 以上)。上限を超えると、エラー終了する。モデルがツールを呼び続けて、終わらなくなることを防ぐ |
| `-c, --cache` | フラグ / 文字列 | `False` | Context Caching を利用。`-c` で最新のキャッシュを自動選択、`--cache=<CACHE_ID>` で特定のキャッシュを指定 (`-c <ID>` のようにスペース区切りにすると、直後の語はプロンプトとして扱われる)。キャッシュのモデルで実行され、システム指示はキャッシュに含まれたものが使われる。`-w` / `--oauth` とは併用できない (エラー終了)。`--mcp` とは引数のエラーにしない。キャッシュを使うリクエストでは、ツール定義を別に指定できないため、Gemini API が 400 (`CachedContent can not be used with GenerateContent request setting system_instruction, tools or tool_config`) を返す想定 (実機では未確認) |
| `-f, --file <PATH>` | 文字列 (複数指定可) | なし | 追加コンテキストとしてロードする (または `-w` の書き込み対象とする) ファイル・ディレクトリパス。`-f a.py -f b.py` のように繰り返して指定。ファイル内容をそのまま送信する用途のため、`--rag` / `--mcp` とは併用できない (指定するとエラー終了) |
| `-m, --model` | 文字列 | `gemini-3.5-flash` | 使用する LLM モデル名 |
| `-p, --provider` | 文字列 | `gemini` | LLM プロバイダ。現在は `gemini` のみ動作 (他の値は未実装) |
| `-w, --write` | フラグ | `False` | 生成・修正結果を対象ファイル (`-f`) に書き込み・適用 (実行前に確認あり) |
| `-a, --auto-save` | フラグ | `False` | 終了時に対話ログを `<日時>_chat.md` として自動保存 |
| `-g, --generate-commit-msg` | フラグ | `False` | Git 差分 (ステージ済みを優先、なければ作業ツリー) からコミットメッセージを生成 |
| `-r, --review` | フラグ | `False` | `-f` 指定ファイル、または Git 差分のコードレビューを実行。Gemini API の一時的なエラー (503 など) はリトライし、失敗した場合は終了コード 1 で終了する |
| `--staged` | フラグ | `False` | `--review` 時に、ステージ済み (`--cached`) の差分を対象にする |
| `-l, --list-models` | フラグ | `False` | 利用可能な LLM モデルの一覧を表示 |
| `--login` | フラグ | `False` | ブラウザで Google アカウントに OAuth ログインし、トークンを `~/.config/code-chat/oauth_token.json` に保存して終了。事前に環境変数 `GEMINI_OAUTH_CLIENT_ID` / `GEMINI_OAUTH_CLIENT_SECRET` の設定が必要 |
| `--oauth` | フラグ | `False` | `GEMINI_API_KEY` ではなく OAuth (`--login` で保存したトークン) で認証する。`GEMINI_API_KEY` が設定されていても OAuth を使う。トークンがなく対話端末の場合は、ブラウザ認証を開始する。RAG (`--rag`, `rag`) の検索は OAuth に対応せず、API キー (`GEMINI_API_KEY`) を使う |
| `-D, --debug` | フラグ | `False` | デバッグログを出力 (`--log-level DEBUG` と同等) |
| `--log-level` | 文字列 | `INFO` | ログレベル (`DEBUG` / `INFO` / `WARNING` / `ERROR` / `CRITICAL`) |
| `--trace` | フラグ | `False` | SDK や HTTP クライアント等のライブラリ内部通信ログを出力。あわせて、Gemini API のエラー時にもトレースバックを出力する (指定しない場合、Gemini API のエラーは、エラー内容だけを出力する。それ以外の例外は、トレースバック付き。ただし、ファイルやディレクトリが見つからないエラーは、概要の 1 行のみ) |
| `--dry-run` | フラグ | `False` | API 呼び出しを行わず、読み込まれるファイル群や指定引数の確認のみ実行 |

標準入力 (パイプ) にテキストがある場合は、`-f` の内容とあわせてコンテキストとして読み込まれます。

### 実行例

```bash
# 通常の対話モード起動
code-chat

# ワンショット実行
code-chat "このコードのバグを修正して" -f ./src/main.py

# パイプ入力をコンテキストにして実行
git diff | code-chat "この変更を要約して"

# RAG 検索を組み合わせてワンショット実行
code-chat "認証機能の実装箇所を抽出して説明して" --rag

# MCP サーバーのツールを使ってワンショット実行
code-chat "git の状態を確認して" --mcp

# RAG で検索したコンテキストをプロンプトに付加して、MCP のツールを使って実行
code-chat "認証機能の実装箇所を調べて、関連する変更履歴を確認して" --rag --mcp

# 対象ファイルを LLM の出力で更新 (確認プロンプトあり)
code-chat "型ヒントを追加して" -f ./src/main.py --write

# Git の変更差分からコミットメッセージを自動生成
code-chat --generate-commit-msg

# 指定ファイルのコードレビュー / Git 差分のレビュー / ステージ済み差分のレビュー
code-chat --review -f ./src/main.py
code-chat --review
code-chat --review --staged

# 利用可能なモデル一覧を取得
code-chat --list-models

# OAuth ログイン (初回のみ。API キーの代わりに Google アカウントで認証)
code-chat --login

# OAuth で実行 (GEMINI_API_KEY が設定されていても OAuth を使う)
code-chat --oauth "こんにちは"

# API を呼ばずに解析結果だけ確認
code-chat "テスト" -f ./src/main.py --dry-run

```

### 対話モード (REPL) のコマンド

対話モードでは、以下の入力を特別に扱います。

| 入力 | 説明 |
| --- | --- |
| `exit` / `quit` / `q` | 対話を終了 (`Ctrl+C` / `Ctrl+D` でも終了) |
| `/save <PATH>` | 対話ログを指定パスに Markdown で保存 |
| `/mcp <PROMPT>` | MCP ツールを使ってプロンプトを実行 (`--mcp` 指定時は通常の入力もすべて MCP 経由) |

---

## 3. 管理用サブコマンド仕様

### 3.1 `rag` (RAG インデックス管理)

Vector DB (既定: `./.chroma_db`) の作成、差分更新、削除、ステータス確認を行います。インデックス作成と検索には Gemini の Embedding API を使用するため、`GEMINI_API_KEY` が必要です。

| コマンド | オプション | 説明 |
| --- | --- | --- |
| `code-chat rag create` | `--input_dirs <PATH>...` `--output_dir <DIR>` | 指定ディレクトリ (複数可、既定: `.`) を走査して Vector DB を新規作成 (既存の内容は初期化) |
| `code-chat rag update` | `--input_dirs <PATH>...` `--output_dir <DIR>` | 指定ディレクトリの内容を既存の Vector DB に反映 (読み込んだファイルの既存のチャンクは置き換え、他のファイルのデータは残す) |
| `code-chat rag rm` | なし | 構築済みの Vector DB (`./.chroma_db`) の内容を削除 |
| `code-chat rag status` | なし | Vector DB のパスと登録済みチャンク数を表示 |

* `--output_dir` の既定値は `./.chroma_db` です。
* インデックス対象は `.py` `.cpp` `.hpp` `.c` `.h` `.ts` `.js` で、`.git` `.venv` `node_modules` などの除外ディレクトリと、`.` で始まる隠しディレクトリはスキップされます。
* `--dry-run` を指定すると、`rag create` / `rag update` は、引数の解析結果に続けて、インデックス対象ファイルの一覧を表示します (Gemini API には接続せず、インデックスも変更しません)。

#### 実行例

```bash
# カレントディレクトリのインデックス作成
code-chat rag create

# 複数ディレクトリを指定して作成
code-chat rag create --input_dirs ./packages ./tests --output_dir ./.chroma_db

# 特定ディレクトリの内容を追加
code-chat rag update --input_dirs ./packages

# DB ステータスの確認
code-chat rag status

# インデックスの削除
code-chat rag rm

# RAG を有効にして質問
code-chat "認証機能の実装箇所を説明して" --rag

```

---

### 3.2 `cache` (Context Caching 管理)

Gemini サーバー上のキャッシュ (Context Caching) を作成・管理します。大きなコンテキストを 1 度だけ送ってキャッシュし、以降の質問で再利用することで、入力トークンの課金と応答時間を抑えます。

| コマンド | 引数 / オプション | 説明 |
| --- | --- | --- |
| `code-chat cache create` | `[PATH]` `--ttl <SECONDS>` | 指定パス (省略時は `.`) のコンテキストを読み込んで新規キャッシュを作成 (デフォルト TTL: 3600秒)。`-m` で指定したモデルに紐づく |
| `code-chat cache update` | `[PATH]` | 同じパスの既存キャッシュを削除し、最新の内容で作り直す (内容は更新できないため再作成。TTL は 3600 秒)。既存がなければ新規作成 |
| `code-chat cache rm` | `[CACHE_ID]` | 指定したキャッシュを削除。省略時は、**このツールで作成した**キャッシュをすべて削除 |
| `code-chat cache list` | なし | このツールで作成したキャッシュの一覧 (ID・対象・モデル・トークン数・有効期限) を表示 |

```bash
# ソースコードをキャッシュして、繰り返し質問する
code-chat cache create ./src --ttl 7200
code-chat -c "認証まわりの実装を説明して"
code-chat --cache=cachedContents/abc123 "テストの足りない箇所は？"

# 内容が変わったら作り直す / 一覧 / 削除
code-chat cache update ./src
code-chat cache list
code-chat cache rm
```

**制約と注意点**

* **有料枠の API キーでのみ利用できます。** 無料枠では、保存できるキャッシュ量の上限が 0 のため、作成が `429 RESOURCE_EXHAUSTED` で失敗します (課金を有効にしたプロジェクトが必要です)。OAuth (`--oauth`) のスコープも対応していないため、`-c` や `cache` サブコマンドと `--oauth` は併用できません。
* コンテキストには最小トークン数 (1024 トークン程度。モデルにより異なります) が必要です。小さいファイルではキャッシュを作成できません。
* キャッシュにはシステム指示が含まれ、作成時のモデルに固定されます。`-c` では、`-m` の指定にかかわらず、キャッシュのモデルで実行します。
* このツールが作成したキャッシュは、`display_name` の先頭の `code-chat:` で識別します。ほかのアプリケーションで作成したキャッシュは、一覧・削除・自動選択の対象になりません。
* キャッシュは、保持時間 (TTL) の間、保存料金が発生します。不要になったら `cache rm` で削除してください。
* **暗黙のキャッシュ**: `-c` を使わなくても、同じ内容を先頭に送り続けると Gemini が自動でキャッシュします。ヒットしたトークン数は、応答後に `キャッシュヒット: 12264 / 16718 トークン (73%)` のようにログへ出力されます (無料枠でも動作します)。

---

### 3.3 `mcp` (MCP サーバー管理)

Model Context Protocol (MCP) サーバーのステータス確認と動作テストを行います。サーバー定義は `~/.config/code-chat/mcp.json` から読み込まれます (詳細は [README.md](README.md) の「MCP の設定と利用」を参照)。

| コマンド | 引数 | 説明 |
| --- | --- | --- |
| `code-chat mcp status` | なし | 有効な MCP サーバーごとに、利用可能なツール一覧を表示 |
| `code-chat mcp test` | `[SERVER_NAME]` | MCP サーバーへの接続とツール一覧取得を試行 (現状は `SERVER_NAME` を指定しても、有効な全サーバーが対象) |

#### 実行例

```bash
# MCP サーバーとツールの一覧を確認
code-chat mcp status

# 全 MCP サーバーの導通テスト
code-chat mcp test

```
