# OAuth ログインの設定手順

`code-chat` は、API キーの代わりに **Google アカウントの OAuth ログイン**で Gemini API を利用できます。このドキュメントでは、Google Cloud での準備から、ログイン、トラブルシューティングまでを説明します。

> **Note:** Google Cloud コンソールの画面や項目の名称は、変更されることがあります。表記が異なる場合は、近い名称の項目を探してください。

---

## 目次

1. [OAuth と API キーの違い](#1-oauth-と-api-キーの違い)
2. [事前に用意するもの](#2-事前に用意するもの)
3. [Google Cloud での設定](#3-google-cloud-での設定)
4. [環境変数の設定](#4-環境変数の設定)
5. [ログイン](#5-ログイン)
6. [動作の仕組み](#6-動作の仕組み)
7. [ログアウト・アカウントの切り替え](#7-ログアウトアカウントの切り替え)
8. [トラブルシューティング](#8-トラブルシューティング)
9. [制限事項](#9-制限事項)
10. [セキュリティ上の注意](#10-セキュリティ上の注意)

---

## 1. OAuth と API キーの違い

| | API キー | OAuth ログイン |
| --- | --- | --- |
| 設定 | `GEMINI_API_KEY` を設定するだけ | OAuth クライアントの作成と、初回ログインが必要 |
| 認証の単位 | キー (誰が使っても同じ) | Google アカウント |
| 有効期限 | なし | アクセストークンは約 1 時間。自動で更新される |
| 指定方法 | 既定 (`GEMINI_API_KEY` を設定) | `--oauth` オプション |
| 対応範囲 | すべての機能 | RAG (`--rag`, `rag` サブコマンド) の検索は API キーを使う |
| 無料枠 | 無料枠のプロジェクトの API キーの枠 | **API キーと同じ** (OAuth にしても増えない。[詳細](#9-制限事項)) |

認証方法は、**`--oauth` オプションの有無で明示的に選択**します。`GEMINI_API_KEY` が設定されていても、`--oauth` を付ければ OAuth が使われます。

| 指定 | 使われる認証 |
| --- | --- |
| `--oauth` なし (既定) | `GEMINI_API_KEY` の API キー。未設定の場合はエラー終了 (OAuth には自動で切り替わりません) |
| `--oauth` あり | 保存済みの OAuth トークン。トークンがなく対話端末から起動した場合は、ブラウザでの OAuth ログインを自動で開始 (非対話環境ではエラー終了) |

---

## 2. 事前に用意するもの

- Google アカウント
- Gemini API を利用する Google Cloud プロジェクト
  - Google AI Studio で API キーを作成済みの場合は、`gen-lang-client-数字` という名前のプロジェクトが自動で作られています。これを使えます。
- ブラウザを開ける環境 (ログイン時に使用します)

---

## 3. Google Cloud での設定

[Google Cloud コンソール](https://console.cloud.google.com/)で、Gemini API を使うプロジェクトを選択して作業します。

### 3-1. Generative Language API を有効にする

1. 「API とサービス」→「ライブラリ」を開く。
2. **Generative Language API** を検索して開く。
3. 「有効にする」を押す (すでに有効な場合は「管理」と表示されます)。

### 3-2. OAuth 同意画面 (Google Auth Platform) を設定する

初めて OAuth クライアントを作る場合は、先に同意画面の設定が必要です。

1. 「API とサービス」→「OAuth 同意画面」(または「Google Auth Platform」) を開く。
2. 「開始」を押し、次の項目を入力する。
   - **アプリ名**: 任意 (例: `code-chat`)。ログイン画面に表示されます。
   - **ユーザー サポートメール**: 自分のメールアドレス
   - **対象 (Audience)**: 個人の Gmail アカウントで使う場合は **外部**
   - **連絡先情報**: 自分のメールアドレス
3. 規約に同意して「作成」を押す。

### 3-3. テストユーザーを追加する

同意画面の公開ステータスが「テスト中」の間は、**テストユーザーに登録したアカウントしかログインできません**。

1. 「Google Auth Platform」→「**対象**」(旧 UI では「OAuth 同意画面」の「テストユーザー」) を開く。
2. 「**+ Add users**」(ユーザーを追加) を押す。
3. ログインに使う Google アカウントのメールアドレスを入力して保存する。

> 登録していないアカウントでログインすると、`エラー 403: access_denied` になります。

### 3-4. OAuth クライアント ID を作成する

1. 「Google Auth Platform」→「**クライアント**」(または「API とサービス」→「認証情報」) を開く。
2. 「クライアントを作成」(「認証情報を作成」→「OAuth クライアント ID」) を押す。
3. **アプリケーションの種類**で **デスクトップ アプリ** を選ぶ。
   - 「ウェブ アプリケーション」を選ぶと、ログイン時に `redirect_uri_mismatch` になります。
4. 名前を入力 (例: `code-chat`) して「作成」を押す。
5. 表示された **クライアント ID** と **クライアント シークレット** を控える。
   - 「JSON をダウンロード」で `client_secret_*.json` として保存することもできます。

> **重要:** クライアント シークレットは他人に見せないでください。ダウンロードした JSON をリポジトリ内に置く場合は、コミットしないよう注意してください (このリポジトリの `.gitignore` では `client_secret*.json` を除外しています)。

### 3-5. (任意) データアクセス (スコープ)

`code-chat` は次の 2 つのスコープを要求します。テスト中のアプリでは、「データアクセス」に事前登録しなくてもログインできます。

| スコープ | 用途 |
| --- | --- |
| `https://www.googleapis.com/auth/cloud-platform` | Gemini API の呼び出し |
| `https://www.googleapis.com/auth/generative-language.retriever` | Generative Language API の利用 |

ログイン時に「このアプリは Google で確認されていません」と表示された場合は、「詳細」→「(アプリ名) に移動 (安全ではないページ)」から進めます。自分が作成したアプリなので問題ありません。

---

## 4. 環境変数の設定

控えたクライアント ID とシークレットを、環境変数に設定します。

| 環境変数 | 内容 |
| --- | --- |
| `GEMINI_OAUTH_CLIENT_ID` | クライアント ID (`....apps.googleusercontent.com`) |
| `GEMINI_OAUTH_CLIENT_SECRET` | クライアント シークレット (`GOCSPX-...`) |

### `~/.zshenv` に登録する (おすすめ)

毎回設定せずに済むよう、`~/.zshenv` などのシェルの設定ファイルに書きます。

```bash
# ~/.zshenv
export GEMINI_OAUTH_CLIENT_ID='your-client-id.apps.googleusercontent.com'
export GEMINI_OAUTH_CLIENT_SECRET='your-client-secret'
```

```bash
# シークレットを含むため、所有者のみ読み書き可能にする
chmod 600 ~/.zshenv

# 現在のシェルに反映する (新しく開いたシェルでは自動で有効)
source ~/.zshenv
```

### シェルに直接設定する (一時的)

```bash
export GEMINI_OAUTH_CLIENT_ID='your-client-id.apps.googleusercontent.com'
export GEMINI_OAUTH_CLIENT_SECRET='your-client-secret'
```

### `.env` ファイルを使う

`.env` はツールが自動では読み込まないため、`export` 形式で書き、シェルで読み込みます。

```bash
# .env
export GEMINI_OAUTH_CLIENT_ID='your-client-id.apps.googleusercontent.com'
export GEMINI_OAUTH_CLIENT_SECRET='your-client-secret'
```

```bash
source .env
```

> `.env` は `.gitignore` の対象です。リポジトリにコミットしないでください。

---

## 5. ログイン

`--login` を実行します。`GEMINI_API_KEY` が設定されていても、そのままで構いません。

```bash
code-chat --login
```

1. ブラウザが開き、Google のログイン画面が表示されます。
2. テストユーザーに登録したアカウントを選び、権限を許可します。
3. ブラウザに `The authentication flow has completed. You may close this window.` と表示されたら、ターミナルに戻ります。
4. `OAuth トークンを保存しました` と表示されれば完了です。

ログイン後は、`--oauth` を付けて実行すると OAuth で認証されます。

```bash
code-chat --oauth "こんにちは"
code-chat --oauth --list-models
```

毎回 `--oauth` を付けたくない場合は、`~/.zshrc` などにエイリアスを設定してください。

```bash
alias code-chat='code-chat --oauth'
```

> **自動ログイン:** `--oauth` を付けて、保存済みのトークンがない場合は、対話端末から `code-chat` を起動すると、自動でブラウザ認証が始まります。パイプ実行などの非対話環境では、`code-chat --login` の実行を促すエラーで終了します。

### 動作確認

```bash
# トークンファイルが作成されていること (権限は -rw-------)
ls -l ~/.config/code-chat/oauth_token.json

# OAuth でモデル一覧が表示されること (GEMINI_API_KEY が設定されていても OAuth が使われる)
code-chat --oauth --list-models
```

---

## 6. 動作の仕組み

- **ログイン**: ローカルに一時的な待ち受けポート (`http://localhost:<ランダムなポート>`) を立て、ブラウザからのリダイレクトで認可コードを受け取ります (ループバック方式)。
- **トークンの保存先**: `~/.config/code-chat/oauth_token.json` (所有者のみ読み書き可能。権限 `0600`)
- **トークンの更新**: アクセストークンは約 1 時間で期限が切れます。期限切れ後の最初のリクエストで、保存済みのリフレッシュトークンから自動で更新し、ファイルも更新します。
- **API 呼び出し**: `Authorization: Bearer <アクセストークン>` ヘッダーを付けて Gemini API を呼び出します。`google-genai` SDK は API キーを必須とするため、内部ではダミーのキーを渡し、送信直前にそのヘッダーを外して Bearer トークンに置き換えています。

---

## 7. ログアウト・アカウントの切り替え

### ログアウト (トークンを削除する)

```bash
rm ~/.config/code-chat/oauth_token.json
```

ローカルのトークンを削除しても、Google 側の許可は残ります。完全に取り消すには、[Google アカウントのサードパーティ アクセス](https://myaccount.google.com/permissions)で、作成したアプリ (アプリ名) のアクセスを削除してください。

### 別のアカウントに切り替える

1. 切り替え先のアカウントを、テストユーザーに追加する。
2. `rm ~/.config/code-chat/oauth_token.json` でトークンを削除する。
3. `code-chat --login` を実行し、ブラウザで切り替え先のアカウントを選ぶ。

---

## 8. トラブルシューティング

| 症状 | 原因 | 対処 |
| --- | --- | --- |
| `エラー 403: access_denied` (「アプリは Google の審査プロセスを完了していません」) | 同意画面が「テスト中」で、ログインしたアカウントがテストユーザーに未登録 | [3-3](#3-3-テストユーザーを追加する) でアカウントを追加する |
| `redirect_uri_mismatch` | OAuth クライアントの種類が「デスクトップ アプリ」ではない | 種類を「デスクトップ アプリ」にしたクライアントを作り直し、環境変数を更新する |
| `invalid_client` / `The OAuth client was not found` | クライアント ID またはシークレットの誤り、クライアントの削除 | 環境変数の値を確認する。クライアントを作り直した場合は、値を更新して再ログインする |
| `OAuth ログインの設定がありません` | `GEMINI_OAUTH_CLIENT_ID` / `GEMINI_OAUTH_CLIENT_SECRET` が未設定 | [4](#4-環境変数の設定) の手順で設定する (`.env` は `source` が必要) |
| `OAuth ログインが必要です. code-chat --login を実行してください.` | `--oauth` で実行したが、保存済みのトークンがなく、非対話環境だった | `code-chat --login` を実行する |
| `再ログインが必要です` / `OAuth トークンの更新に失敗しました` | リフレッシュトークンが失効した (7 日経過、パスワード変更、許可の取り消しなど) | `code-chat --login` で再ログインする |
| 403 `SERVICE_DISABLED` / `API has not been used in project` | プロジェクトで Generative Language API が無効 | [3-1](#3-1-generative-language-api-を有効にする) で有効にする。有効化の反映には数分かかることがあります |
| API キーが使われてしまう | `--oauth` を付けていない (既定は API キー) | `--oauth` を付けて実行する |
| `GEMINI_API_KEY is missing` | `--oauth` なしで実行し、API キーが未設定 | API キーを設定するか、`--oauth` を付けて実行する |
| `OAuth credentials are missing` | `--oauth` を指定したが、OAuth の設定またはトークンがない | 表示されたメッセージに従い、環境変数の設定と `code-chat --login` を行う |
| ブラウザが開かない / リダイレクトが失敗する | SSH 先などの画面のない環境で実行している | ブラウザのある端末でログインするか、API キー (`GEMINI_API_KEY`) を使う |
| ログイン後、`このアプリは Google で確認されていません` と表示される | 未審査のアプリ | 「詳細」から進む ([3-5](#3-5-任意データアクセス-スコープ) 参照) |

---

## 9. 制限事項

- **RAG の検索は OAuth に対応していません。** `--rag` と `rag` サブコマンドは、Embedding API を `langchain-google-genai` 経由で呼び出し、API キーの環境変数を直接参照します。`--rag` と `--oauth` を併用する場合は、`GEMINI_API_KEY` も設定してください。RAG の検索は API キー、Gemini への問い合わせ (MCP を含む) は OAuth で行われます。`GEMINI_API_KEY` が未設定の場合は、エラーメッセージを表示して終了します。
- **同意画面が「テスト中」のままだと、リフレッシュトークンは 7 日で失効します。** 失効すると再ログインが必要です。
  - 個人利用で頻繁な再ログインを避けたい場合は、同意画面の公開ステータスを「**本番環境**」に変更します。審査は不要ですが、ログイン時に「未確認のアプリ」の警告が表示され、ユーザー数は 100 人までに制限されます。
- **ブラウザが必要です。** 画面のない環境 (SSH 先、CI など) でのログインには向きません。
- **無料枠・料金**は、認証方法ではなくプロジェクトの Gemini API の設定に依存します。**`--oauth` にしても、無料枠は API キーと同じで、増えません。**
  - 実際に確認した結果 (2026-09-26、`gemini-3.5-flash`): `--oauth` でも、無料の API キーでも、429 のエラーは、同じ上限 (`GenerateRequestsPerMinutePerProjectPerModel-FreeTier`、1 分あたり 5 リクエスト、指標 `generate_content_free_tier_requests`) を示しました。
  - 上限は、OAuth クライアントを作成したプロジェクトの、Gemini API の無料枠です。1 日あたりの上限の値は、確認していません。
  - 別製品の **Gemini CLI** の「Google アカウントでログイン」は、別の枠 (公式のドキュメントでは 1 日 1,000 リクエスト) です。code-chat の `--oauth` は Gemini API に直接アクセスするため、この枠は使えません。

---

## 10. セキュリティ上の注意

- クライアント シークレット、ダウンロードした `client_secret_*.json`、`oauth_token.json` は、**リポジトリにコミットしない**でください。
- `oauth_token.json` には、アカウントにアクセスできるリフレッシュトークンが含まれます。共有や公開をしないでください。ツールは、このファイルを所有者のみ読み書き可能な権限 (`0600`) で保存します。
- 認証情報が漏れた可能性がある場合は、次の対応をしてください。
  1. Google Cloud コンソールの「クライアント」で、クライアント シークレットをリセット (または、クライアントを削除して作り直し) する。
  2. [Google アカウントのサードパーティ アクセス](https://myaccount.google.com/permissions)で、アプリのアクセスを削除する。
  3. `rm ~/.config/code-chat/oauth_token.json` でローカルのトークンを削除する。
