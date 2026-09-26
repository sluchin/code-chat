# Gemini API エラーの一覧と対処

`code-chat` を使うときに出会う Gemini API のエラーを、原因と対処ごとにまとめます。実際に遭遇したエラーの文言 (メッセージは英語のまま) と、`code-chat` の動作 (リトライ、表示するメッセージ) も載せています。

> **Note:** 上限値 (無料枠のリクエスト数など) やメッセージの文言は、Google 側の都合で変わることがあります。ここに載せた数値は、実際に観測した時点のものです。

---

## 目次

1. [エラーコード別の早見表](#1-エラーコード別の早見表)
2. [遭遇したエラーの詳細](#2-遭遇したエラーの詳細)
3. [code-chat のリトライ動作とエラー表示](#3-code-chat-のリトライ動作とエラー表示)
4. [code-chat が表示するメッセージ](#4-code-chat-が表示するメッセージ)
5. [切り分けの手順](#5-切り分けの手順)
6. [関連ドキュメント](#6-関連ドキュメント)

---

## 1. エラーコード別の早見表

「確認済み」は、このプロジェクトで実際に出会ったものです。それ以外は、Gemini API の一般的な仕様に基づく一覧です。

| HTTP | status | 主な原因 | 確認済み | code-chat の動作 | 詳細 |
| --- | --- | --- | --- | --- | --- |
| 400 | `INVALID_ARGUMENT` | API キーが無効 / キャッシュ対象が小さすぎる / リクエストの形式が不正 | ✅ | リトライしない。`Gemini API エラーにより処理を中断しました` で終了 (終了コード 1) | [2.5](#25-400-api-キーが無効), [2.6](#26-400-キャッシュ対象が小さすぎる) |
| 400 | `FAILED_PRECONDITION` | 無料枠が利用できない地域で、課金が未設定 | - | リトライしない。概要とヒントを出力して、終了コード 1 | [3.4](#34-エラーの表示形式) |
| 403 | `PERMISSION_DENIED` | OAuth のスコープが不足 / API キーやアカウントに権限がない | ✅ | リトライしない。終了コード 1 | [2.7](#27-403-oauth-のスコープが不足) |
| 404 | `NOT_FOUND` | モデルの提供終了 / 存在しないモデルやキャッシュの指定 | ✅ | リトライしない。終了コード 1 | [2.4](#24-404-モデルが提供終了) |
| 429 | `RESOURCE_EXHAUSTED` | 無料枠の 1 日上限 / 無料枠でのキャッシュ保存 / 1 分あたりの上限 (RPM・TPM) | ✅ | 1 日上限はリトライしない。それ以外はリトライ (3 章) | [2.1](#21-429-無料枠の-1-日あたりのリクエスト上限), [2.2](#22-429-無料枠でのキャッシュ保存) |
| 500 | `INTERNAL` | Google 側の一時的な内部エラー | - | リトライしない。概要とヒントを出力して、終了コード 1 | [3.4](#34-エラーの表示形式) |
| 503 | `UNAVAILABLE` | モデルの高負荷 (一時的) | ✅ | リトライする (3 章) | [2.3](#23-503-モデルが高負荷) |
| 504 | `DEADLINE_EXCEEDED` | 入力が大きすぎて、時間内に処理が終わらなかった | - | リトライしない。概要とヒントを出力して、終了コード 1 | [3.4](#34-エラーの表示形式) |

---

## 2. 遭遇したエラーの詳細

### 2.1 429 無料枠の 1 日あたりのリクエスト上限

**メッセージ (抜粋)**

```
429 RESOURCE_EXHAUSTED. You exceeded your current quota, please check your plan and billing details.
* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 20, model: gemini-3.8-flash
  quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier
```

- **原因**: 無料枠の API キーで、モデルごとの 1 日あたりのリクエスト数の上限に達した (観測時は `gemini-3.8-flash` で 20 件)。上限は、モデルごとに別々に数えられる。
- **code-chat の動作**: メッセージに `PerDay` が含まれるため、**リトライしません** (待っても回復しないため)。概要とヒントを 1 回だけ出力して、終了コード 1 で終了します ([3.4](#34-エラーの表示形式))。
- **対処**:
  - 翌日 (上限のリセット後) まで待つ。
  - 別のモデルを `-m` で指定する (上限はモデルごと)。
  - 課金を有効にした有料枠のプロジェクトの API キーを使う。

### 2.2 429 無料枠でのキャッシュ保存

**メッセージ**

```
429 RESOURCE_EXHAUSTED. TotalCachedContentStorageTokensPerModelFreeTier limit exceeded for model gemini-3.8-flash: limit=0, requested=16713
```

- **原因**: Context Caching (`cache create`) で保存できるトークン量の上限が、無料枠では **0** のため。
- **code-chat の動作**: `無料枠では Context Caching を利用できません (課金を有効にした有料枠のプロジェクトが必要です)` と表示して終了します (終了コード 1)。
- **対処**: 有料枠の API キーを使う。詳しくは [COMMANDS.md の `cache`](COMMANDS.md#32-cache-context-caching-管理) を参照。

### 2.3 503 モデルが高負荷

**メッセージ**

```
503 UNAVAILABLE. This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.
```

- **原因**: モデル側のアクセスが集中している (一時的)。認証やコードの問題ではない。
- **code-chat の動作**: 自動でリトライします (初回を含めて最大 5 回試行し、待ち時間は、指数バックオフにジッターを加えた秒数、または `retryDelay` に従う)。詳しくは [3 章](#3-code-chat-のリトライ動作とエラー表示)。
- **対処**: 通常は、待つだけで回復する。繰り返す場合は、少し時間をおいて再実行するか、別のモデルを `-m` で指定する。

### 2.4 404 モデルが提供終了

**メッセージ (抜粋)**

```
404 NOT_FOUND. This model models/gemini-2.5-flash is no longer available to new users. Please update your code to use models/gemini-3.8-flash for the latest features and improvements.
```

- **原因**: 指定したモデルが、新規ユーザーに提供終了になった。
- **code-chat の動作**: リトライせずに終了します (終了コード 1)。
- **対処**: `code-chat --list-models` で利用できるモデルを確認し、`-m` で指定し直す。特定のバージョンを固定せず、`gemini-flash-latest` のようなエイリアスを使う方法もある (指す先のモデルは、Google が更新する)。

### 2.5 400 API キーが無効

**メッセージ**

```
400 INVALID_ARGUMENT. API key not valid. Please pass a valid API key.
```

- **原因**: `GEMINI_API_KEY` の値が誤っている、失効している、または削除された。
- **code-chat の動作**: リトライせずに終了します (終了コード 1)。
- **対処**: [Google AI Studio](https://aistudio.google.com/apikey) で API キーを確認し、`GEMINI_API_KEY` を設定し直す。値の前後に空白や改行が入っていないかも確認する。

### 2.6 400 キャッシュ対象が小さすぎる

**メッセージ**

```
400 INVALID_ARGUMENT. Cached content is too small. total_token_count=2, min_total_token_count=1024
```

- **原因**: `cache create` の対象が、キャッシュに必要な最小トークン数 (観測時は 1024) に満たない。
- **code-chat の動作**: `キャッシュ対象のコンテキストが小さすぎます (最小 1024 トークン)` と表示して終了します (終了コード 1)。
- **対処**: 対象のファイルやディレクトリを増やす。小さいコンテキストは、キャッシュしなくても、通常のリクエストで十分。

### 2.7 403 OAuth のスコープが不足

**メッセージ (抜粋)**

```
403 PERMISSION_DENIED. Request had insufficient authentication scopes.
reason: ACCESS_TOKEN_SCOPE_INSUFFICIENT
method: google.ai.generativelanguage.v1beta.CacheService.CreateCachedContent
```

- **原因**: OAuth のトークンのスコープ (`cloud-platform` と `generative-language.retriever`) では、キャッシュ用の API (`CreateCachedContent`) を呼べない。
- **code-chat の動作**: Context Caching は API キー専用のため、`--oauth` と `-c` / `cache` の併用を、引数の解析時にエラーにします (終了コード 2)。
- **対処**: Context Caching を使うときは、`--oauth` を付けず、API キー (有料枠) を使う。

### 2.8 `google-genai` SDK の `ValueError` (OAuth との関係)

Gemini API を OAuth で使うために、`code-chat` は SDK の外側で `Authorization` ヘッダーを付けています (詳しくは [OAUTH.md](OAUTH.md#6-動作の仕組み))。これは、SDK が OAuth の認証情報を直接受け付けないためです。

```
ValueError: No API key was provided. Please pass a valid API key.
ValueError: Credentials and API key are mutually exclusive in the client initializer.
```

- `code-chat` を使う限り、ユーザーがこのエラーを見ることはありません。SDK を直接呼び出す自作スクリプトで、`credentials` を渡したときに出ます。

---

## 3. code-chat のリトライ動作とエラー表示

### 3.1 リトライ (すべての Gemini API 呼び出しで共通)

Gemini API の呼び出しは、すべて `call_with_retry` (`tenacity` を使用) を通します。チャット、コミットメッセージ生成、`--review`、`--list-models`、`cache` の各コマンド、`--mcp` が、同じ方針でリトライされます。SDK (`google-genai`) 自身のリトライは、二重にならないよう、無効にしています。

| 項目 | 内容 |
| --- | --- |
| リトライの対象 | HTTP 503 / 429、またはメッセージに `503` / `UNAVAILABLE` / `429` / `RESOURCE_EXHAUSTED` を含むエラー、およびネットワークの一時的なエラー (接続失敗、タイムアウトなど) |
| リトライしない | 上記以外 (400、403、404 など)、および **1 日あたりの上限** (メッセージに `PerDay` を含む 429) |
| 回数 | 初回を含めて最大 5 回試行する (リトライは最大 4 回) |
| 待ち時間 | 指数バックオフ (1 秒から始めて 2 倍ずつ、最大 60 秒) に、ジッター (最大 1 秒のランダムな揺らぎ) を加える |
| 待ち時間の優先 | エラーに `retryDelay` (例: `retryDelay: '30s'`) が含まれる場合は、その秒数 + 1 秒 |
| リトライ中の表示 | `Gemini API で一時的なエラーが発生しました (1/5): [HTTP 429 RESOURCE_EXHAUSTED] 1 分あたりのリクエスト上限に到達しました ... 約 59 秒後に再試行できます. 60.0秒後に再試行します...` |
| ストリーミング | 最初のチャンクを受信するまでが、リトライの対象。出力が始まったあとにエラーになった場合は、出力の重複を避けるため、**リトライしない** |
| 最終的に失敗 | 概要とヒントを 1 回だけ出力して、終了コード 1 で終了する ([3.4](#34-エラーの表示形式)) |

リトライの設定値 (試行回数、待ち時間など) は、`RetryPolicy` クラスの定数として、一元管理しています。

RAG (`langchain` 経由の呼び出し) も、同じリトライの対象です。

- 埋め込み (検索時のクエリ、インデックス作成時の 32 件ごとのバッチ): `RetryEmbeddings` が `call_with_retry` を通す。失敗したバッチだけをやり直す。
- `langchain` が `APIError` やネットワークのエラー (`httpx` のタイムアウトや接続のエラー) を別の例外で包む場合も、原因を辿って判定する (`retryDelay` も原因から取り出す)。

### 3.2 MCP 連携 (`--mcp`)

MCP 連携でも、3.1 と同じリトライを使います (503 と 429、ネットワークの一時的なエラー)。1 日あたりの上限は、リトライしません。最終的に失敗した場合は、概要とヒントを出力します。対話モードでは、そのまま次の入力に進み、ワンショット実行では、終了コード 1 で終了します。

### 3.3 例外の扱い (`main`)

| 例外 | 動作 |
| --- | --- |
| `APIError` / `ServerError` / `ClientError` | `Gemini API エラーにより処理を中断しました: <概要とヒント>` を出力して、終了コード 1 (トレースバックは出力しない) |
| `KeyboardInterrupt` / `EOFError` (Ctrl+C など) | `会話を終了します` を出力して、終了コード 0 |
| `FileNotFoundError` / `ValueError` / `PermissionError` | `ファイル操作でエラーが発生しました` を出力して、終了コード 1 |
| その他の例外 | `予期せぬエラーが発生しました` を出力して、終了コード 1 (`-D` を付けるとトレースバックも出力) |

### 3.4 エラーの表示形式

Gemini API のエラーは、どのコマンド (チャット、`--review`、`--list-models`、`--generate-commit-msg`、`--mcp`、`cache`、`rag`) でも、次の形式で **1 回だけ**表示します。レスポンスの辞書の全文は出力しません。

```
Gemini API エラーにより処理を中断しました: [HTTP 429 RESOURCE_EXHAUSTED] 無料枠の 1 日あたりのリクエスト上限に到達しました (モデル: gemini-3.8-flash, 上限: 20 件)
  ヒント: 1 日あたりの上限は, 翌日まで回復しません. 別のモデルを -m で指定するか, 課金を有効にした API キーを使ってください.
```

概要は、`quotaId` などから、原因を区別して作ります。判別に使う値 (HTTP ステータス、`status`、`PerDay` などの文字列) は、コード中に直接書かず、`GeminiErrorKind` クラスの定数として一元管理しています。

| 原因 | 概要の例 | ヒント |
| --- | --- | --- |
| 429 (1 日あたりの上限) | 無料枠の 1 日あたりのリクエスト上限に到達しました (モデル、上限) | 翌日まで回復しない。別のモデルか、有料枠にする |
| 429 (1 分あたりの上限) | 1 分あたりのリクエスト上限に到達しました (約 30 秒後に再試行できます) | しばらく待つ。自動でリトライされる |
| 429 (無料枠でのキャッシュ保存) | 無料枠では Context Caching を利用できません | 有料枠の API キーを使う |
| 429 (その他) | リクエストの上限に到達しました | 原因の候補 (無料枠の上限、TPM、RPM) |
| 503 | モデルが高負荷で、一時的に利用できません | 少し待つか、別のモデルにする |
| 404 | 指定したモデルまたはリソースが見つかりません | `--list-models` で確認する |
| 400 (無効な API キー) | API キーが無効です | `GEMINI_API_KEY` を確認する |
| 400 (キャッシュ対象が小さい) | キャッシュ対象のコンテキストが小さすぎます (最小 1024 トークン) | 対象を増やす |
| 403 (OAuth のスコープ不足) | OAuth のトークンのスコープが不足しています | Context Caching は API キーのみ |
| 400 (前提条件を満たさない) | この地域では、課金の設定なしに利用できません | 請求先アカウントの設定を確認する |
| 500 | Google 側で内部エラーが発生しました | しばらく待って再実行する |
| 504 | 処理が制限時間内に終わりませんでした (タイムアウト) | コンテキストを減らして再実行する |

追加の情報が必要なときは、次のオプションを使います。

- `-D` (デバッグ): レスポンスの詳細 (辞書の全文) を、DEBUG ログとして出力します。
- `--trace`: 概要に加えて、**トレースバック**も出力します (あわせて、`httpx` などのライブラリの通信ログも出力します)。

Gemini API 以外の例外 (ファイル操作、内部のバグなど) は、`--trace` なしでも、トレースバックを出力します。ただし、ファイルやディレクトリが見つからないエラー (`FileNotFoundError`。パスの指定ミスなど、原因が明らかなもの) は、`--trace` を指定しない限り、概要の 1 行だけを出力し、トレースバックは `-D` で出力します。

---

## 4. code-chat が表示するメッセージ

Gemini API のエラーではなく、`code-chat` 自身が、認証情報やキャッシュの問題を検出したときのメッセージです。

### 認証

| メッセージ | 原因と対処 |
| --- | --- |
| `GEMINI_API_KEY is missing` | API キーが未設定。`export GEMINI_API_KEY=...` を設定する。OAuth を使う場合は、`--oauth` を付ける |
| `OAuth credentials are missing` | `--oauth` を指定したが、OAuth の設定または保存済みのトークンがない。表示される手順に従って、環境変数の設定と `code-chat --login` を行う |
| `OAuth ログインが必要です. code-chat --login を実行してください.` | トークンがなく、非対話環境 (パイプなど) で実行した。`code-chat --login` を実行する |
| `OAuth トークンの更新に失敗しました. code-chat --login で再ログインしてください.` | リフレッシュトークンが失効した。`code-chat --login` で再ログインする |
| `RAG には API キーが必要です. GEMINI_API_KEY を設定してください` | `--rag` は、`--oauth` 指定時も API キーを使う。`GEMINI_API_KEY` を設定する |

OAuth のログイン時のエラー (`access_denied`、`redirect_uri_mismatch`、`invalid_client` など) は、[OAUTH.md のトラブルシューティング](OAUTH.md#8-トラブルシューティング)を参照してください。

### Context Caching

| メッセージ | 原因と対処 |
| --- | --- |
| `無料枠では Context Caching を利用できません ...` | [2.2](#22-429-無料枠でのキャッシュ保存) を参照 |
| `コンテキストが小さすぎます ...` | [2.6](#26-400-キャッシュ対象が小さすぎる) を参照 |
| `'<PATH>' にキャッシュ対象のファイルがありません` | 対象パスに、読み込めるテキストファイルがない。パスを確認する |
| `使用できるキャッシュがありません. code-chat cache create で作成してください` | `-c` を指定したが、このツールで作成したキャッシュがない (TTL 切れを含む)。`cache create` で作成する |
| `キャッシュ '<ID>' を取得できませんでした` | `--cache=<ID>` の ID が存在しない、または期限切れ。`cache list` で確認する |
| `-c/--cache は -w/--write と併用できません` など | 引数の組み合わせが不正 (終了コード 2)。`-c` は、`-w` / `--oauth` と併用できない。`--mcp` との併用は、引数のエラーにせず、Gemini API のエラー (400 の想定、実機では未確認) に任せる |

---

## 5. 切り分けの手順

1. **HTTP ステータスを確認する**: `code-chat` は、`Gemini API エラーが発生しました [HTTP 429]: ...` のように、ステータスとメッセージをログに出力します。詳細が必要なときは、`-D` (デバッグ) や `--trace` (トレースバックと通信ログ) を付ける。
2. **429 の場合**: メッセージの `quotaId` を見る。
   - `...PerDay...` → 1 日の上限。翌日まで待つ、別のモデルにする、または有料枠にする ([2.1](#21-429-無料枠の-1-日あたりのリクエスト上限))。
   - `...CachedContentStorage...FreeTier` → 無料枠ではキャッシュを使えない ([2.2](#22-429-無料枠でのキャッシュ保存))。
   - それ以外 → 1 分あたりの上限。少し待つ (自動でリトライされる)。
3. **503 の場合**: 一時的な高負荷。自動でリトライされるので、待つ ([2.3](#23-503-モデルが高負荷))。
4. **404 の場合**: モデル名を確認する。`code-chat --list-models` で、利用できるモデルを調べる ([2.4](#24-404-モデルが提供終了))。
5. **400 / 403 の場合**: API キー ([2.5](#25-400-api-キーが無効))、または OAuth のスコープ ([2.7](#27-403-oauth-のスコープが不足)) を確認する。
6. **`code-chat` 自身のメッセージ**の場合: [4 章](#4-code-chat-が表示するメッセージ)の表を確認する。

---

## 6. 関連ドキュメント

- [README.md](README.md): セットアップ、認証の設定、トラブルシューティング
- [COMMANDS.md](COMMANDS.md): コマンドとオプションの一覧 (`cache` の制約を含む)
- [OAUTH.md](OAUTH.md): OAuth ログインの設定手順とトラブルシューティング
- [Gemini API のエラーコード (公式)](https://ai.google.dev/gemini-api/docs/troubleshooting)
- [Gemini API のレート制限 (公式)](https://ai.google.dev/gemini-api/docs/rate-limits)
