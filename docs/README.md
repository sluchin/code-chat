### `DOCUMENTATION.md`（ドキュメント構築・運用マニュアル）

```markdown
# ドキュメント構築・運用ガイド

本プロジェクトでは、Python コード内の Docstring（Google Style）から [Sphinx](https://www.sphinx-doc.org/) を使用して自動的に API リファレンスおよび HTML ドキュメントを生成します。

パッケージマネージャーおよび実行環境には `uv` を使用します。

---

## 1. 事前準備

プロジェクトの依存関係（Sphinx および開発用ツール）をインストールします。

```bash
# プロジェクトルートで実行
uv sync

```

※ まだ依存関係に追加していない場合は以下を実行してください:

```bash
uv add --dev sphinx sphinx-autobuild furo

```

---

## 2. ドキュメントのビルド手順

### 方法 A: API ドキュメント再生成 + HTML ビルド（推奨）

コード内の Docstring を変更した場合や新しいモジュールを追加した場合は、`.rst` ファイルを更新してビルドします。

```bash
cd docs
make apidoc

```

> **Note:** `make apidoc` は `sphinx-apidoc` で `.rst` を最新化してから HTML を生成するカスタムターゲットです。

---

### 方法 B: 通常の HTML ビルド

`.rst` ファイルの変更のみ（文言の修正など）の場合は、標準の `make` コマンドでビルドできます。

```bash
cd docs
uv run make html

```

生成された HTML は `docs/_build/html/index.html` からブラウザで閲覧できます。

---

## 3. リアルタイムプレビュー（開発時）

ドキュメントの執筆中やスタイルの確認時には、ファイルを保存するたびに自動で再ビルドしてブラウザをリロードする `sphinx-autobuild` を使用すると便利です。

```bash
# プロジェクトルートから実行
uv run sphinx-autobuild docs docs/_build/html

```

起動後、ターミナルに表示される URL（例: `http://127.0.0.1:8000`）にブラウザでアクセスしてください。

---

## 4. プロジェクト構造と設定ファイル

```text
.
├── DOCUMENTATION.md        # 本ガイド
├── pyproject.toml          # uv の依存関係管理
├── src/                    # Python ソースコード
└── docs/                   # Sphinx ドキュメント用ディレクトリ
    ├── conf.py             # Sphinx 設定ファイル (パス指定、拡張子、テーマ設定)
    ├── index.rst           # ドキュメントのトップページ（目次）
    ├── api/                # sphinx-apidoc によって自動生成される .rst 群
    ├── Makefile            # ビルド用コマンド設定
    └── _build/             # 生成された HTML の出力先 (git 追跡対象外)

```

---

## 5. Makefile の設定 (`docs/Makefile`)

`make apidoc` を有効にするため、`docs/Makefile` の末尾に以下のターゲットが記述されていることを確認してください。

```make
# apidoc と html ビルドを一括実行するターゲット
apidoc:
	uv run sphinx-apidoc -f -o api ../src/gemini_app
	@$(SPHINXBUILD) -M html "." "$(BUILDDIR)" $(SPHINXOPTS) $(O)

```

---

## 6. Docstring の記述ルール

本プロジェクトの Python コードは **Google Style Python Docstrings** に準拠して記述します。

```python
def example_function(param1: str, param2: int = 0) -> bool:
    """関数の概要を1行で記述（末尾はピリオド）.

    詳細な説明をここに記述します.

    Args:
        param1 (str): パラメータ1の説明.
        param2 (int, optional): パラメータ2の説明. Defaults to 0.

    Returns:
        bool: 戻り値の説明.

    Raises:
        ValueError: エラー条件の説明.
    """
    return True
```

```
