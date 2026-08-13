# code-chat

Gemini API やローカル LLM を使用してローカルソースコードの参照・対話・自動更新を行う CLI ツール。

## 主な機能 (Features)

`code-chat` は、ローカルのソースコード構造を理解し、CLI 上で直接コードの参照・修正・コミット作成までを完結させるための開発者向け AI ツールです。

- 💬 **ローカルコードベースとの対話 (Interactive Chat)**
  - 指定したディレクトリやファイルをコンテキストとして読み込み、コードの挙動解説やバグ修正案を対話形式で確認できます。

- ✏️ **ファイルへの直接書き込み・自動更新 (`-w`, `--write`)**
  - LLM が生成したコードを直接ローカルファイルへ自動上書き・反映します。
  - **安全設計**: 不完全な省略コード（`...` など）を検知して誤上書きを防ぐ `is_partial_code` チェックおよびサニタイズ処理、実行前の確認プロンプトを搭載。

- 📝 **Git コミットメッセージの自動生成 (`-g`, `--generate-commit-msg`)**
  - `git diff` の変更内容を分析し、Conventional Commits 形式に沿った適切なコミットメッセージを提案・生成します。

- 🔌 **マルチ LLM / プロバイダー対応予定 (Multi-LLM Support)**
  - Gemini API をはじめ、Ollama（ローカル LLM）など複数バックエンドへの柔軟な切り替えを見据えた設計。

- 🛡️ **堅牢なコード品質保証**
  - POSIX 標準（ファイル末尾の改行コード保証）に準拠したフォーマット出力。
  - `ruff` / `mypy` / `pytest` / `pre-commit` をフル活用したクリーンな開発基盤。

## 前提条件

- **Python**: 3.10 以上
- **uv**: パッケージ管理ツール ([インストール方法](https://docs.astral.sh/uv/))

## セットアップ・インストール手順

リポジトリを clone した後、用途に合わせて開発環境のセットアップまたは CLI ツールとしてのインストールを行います。

### 1. 開発環境のセットアップ

```bash
# 1. リポジトリの clone と移動
git clone <repository-url>
cd gemini-app

# 2. 仮想環境の作成と依存ライブラリの同期 (uv.lock に基づいて自動インストール)
uv sync

# 3. pre-commit フックの有効化 (コミット時の自動コードチェック)
uv run pre-commit install

```

### 2. gemini-app のインストール (CLIツールとしての利用)

`uv tool` を使用すると、環境を汚さずに CLI コマンドとしてグローバルにインストールできます。

```bash
# ローカルリポジトリから CLI ツールとしてインストール
uv tool install .

# インストール後は直接コマンドとして呼び出し可能
gemini-app

```

> **Note:** 開発中の変更を即座に反映させたい場合は、編集可能モード（Editable install）でインストールします。
> ```bash
> uv tool install --editable .
>
> ```
>
>

## 環境変数の設定

プロジェクトルートに `.env` ファイルを作成し、Gemini API キーを設定してください。

```bash
# .env
GEMINI_API_KEY=your_api_key_here

```

## 実行方法

`uv run` を使用してスクリプトを実行するか、インストールした `gemini-app` コマンドを実行します。

```bash
# uv run 経由で実行
uv run gemini-app

# または直接実行（uv tool install 済みの場合）
gemini-app

```

## テストの実行

`pytest` を使用してテストおよびカバレッジ測定を実行します。

```bash
# 単体テストの実行
uv run pytest

# カバレッジレポート付きで実行
uv run pytest --cov=gemini_app --cov-report=term-missing

```

## コード品質チェック・開発用コマンド

コミット前や開発中に手動でコードチェックや `pre-commit` を実行できます。

```bash
# フォーマットとリンターチェック (Ruff)
uv run ruff check --fix .
uv run ruff format .

# 詳細リンターチェック (Pylint)
uv run pylint src/

# 静的型チェック (Mypy)
uv run mypy src/

# pre-commit フックの手動実行 (全ファイル対象)
uv run pre-commit run --all-files

# pre-commit フックの更新
uv run pre-commit autoupdate

```
