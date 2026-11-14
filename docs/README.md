# ドキュメントの作り方

Python のコードの Docstring (Google Style) から、[Sphinx](https://www.sphinx-doc.org/) で API リファレンスの HTML を作ります。パッケージの管理と実行には `uv` を使います。

## 1. 準備

依存関係 (Sphinx と開発用のツール) を入れます。

```bash
# リポジトリの直下で実行する
uv sync
```

## 2. ビルド

### API の `.rst` を作り直して、HTML をビルドする

Docstring を変えたときや、モジュールを足したときに使います。

```bash
cd docs
make apidoc
```

`make apidoc` は、`sphinx-apidoc` で `api/` の `.rst` を作り直してから、HTML を作ります (`docs/Makefile` の独自のターゲット)。

### HTML だけをビルドする

`.rst` の文言だけを変えたときに使います。

```bash
cd docs
make html
```

HTML は `build/docs/html/index.html` にできます (`docs/Makefile` の `BUILDDIR` は `../build/docs`)。

## 3. 書きながら確かめる

`sphinx-autobuild` は、ファイルを保存するたびに、ビルドし直して、ブラウザを読み込み直します。

```bash
# リポジトリの直下で実行する
uv run sphinx-autobuild docs build/docs/html
```

起動すると、端末に URL (例: `http://127.0.0.1:8000`) が出ます。

## 4. 構成

```text
.
├── pyproject.toml          # uv の依存関係 (workspace)
├── packages/               # Python のソース (uv workspace)
│   ├── code-chat-cli/      #   CLI の本体 (code_chat_cli)
│   ├── code-chat-rag/      #   RAG (code_chat_rag)
│   └── code-chat-mcp/      #   MCP (code_chat_mcp)
├── docs/                   # Sphinx のドキュメント
│   ├── conf.py             #   Sphinx の設定 (パス, 拡張, テーマ sphinx_rtd_theme)
│   ├── index.rst           #   トップページ (目次)
│   ├── api/                #   sphinx-apidoc が作る .rst (パッケージごと)
│   └── Makefile            #   ビルドのコマンド (apidoc のターゲットを含む)
└── build/docs/             # 生成した HTML (git の対象外)
```

## 5. Docstring の書き方

Python のコードは、**Google Style Python Docstrings** で書きます。

```python
def example_function(param1: str, param2: int = 0) -> bool:
    """関数の概要を 1 行で書く (末尾はピリオド).

    詳しい説明をここに書く.

    Args:
        param1 (str): パラメータ 1 の説明.
        param2 (int, optional): パラメータ 2 の説明. Defaults to 0.

    Returns:
        bool: 戻り値の説明.

    Raises:
        ValueError: エラーの条件の説明.
    """
    return True
```
