# code-chat-rag

`code-chat-rag` は, ローカルコードベースに対する RAG (Retrieval-Augmented Generation) の, 検索の部分を提供するパッケージです. ソースコードのチャンク化, ベクトルストア (ChromaDB) への保存, 質問に関連するコードの取得を行います.

回答の生成は, このパッケージでは行いません. 取得したコード (コンテキスト) を, 呼び出し側 (`code-chat-cli`) が, 質問に付加して Gemini に送ります.

---

## 主なコンポーネント

* **`Indexer`**: 指定したディレクトリ配下のソースコードを読み込み, 言語ごとの構文 (関数やクラスの区切りなど) を考慮して, メタデータ (ファイルパスなど) を保持したチャンクに分割します.
* **`VectorStore`**: ChromaDB を使い, チャンクの埋め込み (Embedding) の保存, 類似度検索, ソースファイル単位の削除を管理します. 埋め込みには, Gemini の `gemini-embedding-001` を使います.
* **`RagService`**: インデックスの作成・更新, 関連するコードの取得, 削除, ステータスの取得を統括する, 高レベルのサービスです.
* **`RetryEmbeddings`**: 埋め込みの呼び出しを, `code_chat_lib.api.call_with_retry` 経由で実行し, Gemini API の一時的なエラー (503 / 429) をリトライします.

---

## 使い方

埋め込みには Gemini の API を使うため, 環境変数 `GEMINI_API_KEY` (または `GOOGLE_API_KEY`) が必要です.

### 1. リポジトリのインデックスを作成する

指定したディレクトリ配下のソースコードを読み込み, ChromaDB に保存します. 戻り値は, 保存したチャンクの数です.

```python
from code_chat_rag import RagService

service = RagService(output_dir="./.chroma_db")

# 新規作成: 既存の内容を消して, 全件を作り直す
chunk_count = service.index_repository(["/path/to/target/repo"])

print(f"Indexed {chunk_count} chunks successfully.")
```

### 2. 差分更新する

`update_only=True` を指定すると, 読み込んだファイルの既存のチャンクを置き換えて (同じファイルのチャンクが重複しないよう, 先に削除してから追加), 他のファイルのデータは残します.

```python
chunk_count = service.index_repository(["/path/to/target/repo"], update_only=True)
```

### 3. 質問に関連するコードを取得する

質問に類似したチャンクを検索し, ファイルパス付きの文字列に整形して返します (`k` は取得するチャンク数, 既定は 5).

```python
context = service.get_context("ChromaDB への接続処理を行っているモジュールはどれですか？", k=5)
print(context)
# --- File: packages/code-chat-rag/src/code_chat_rag/vector_store.py ---
# ...
```

### 4. ステータスの確認と削除

```python
print(service.get_status())  # データベースのパスと, 登録済みのチャンク数
service.clear()              # ベクトルストアの内容を削除
```

### インデックスの対象

`Indexer` は, 次のファイルを対象にします.

* 拡張子: `.py` `.cpp` `.hpp` `.c` `.h` `.ts` `.js` (`suffixes` 引数で変更できます).
* 除外: `.git` `.venv` `node_modules` `__pycache__` `build` `dist` などの除外ディレクトリ (`code_chat_lib.constants.Constants.EXCLUDE_DIRS`) と, `.` で始まる隠しディレクトリ. 走査を始める場所として指定したパス自体は, 判定の対象外です.

インデックスを作らずに, 対象のファイルだけを確認するには, `Indexer.get_target_files()` を使います.

```python
from code_chat_rag import Indexer

print(Indexer(input_dirs=["/path/to/target/repo"]).get_target_files())
```

---

## アーキテクチャ概要

```text
[ Source Code ]
       │
       ▼  (Indexer)
[ Document Chunks ]
       │
       ▼  (VectorStore / ChromaDB + RetryEmbeddings)
[ Vector Index ] ◄──────── index_repository (RagService)
       │
       ▼  (Retriever)
[ Related Code ] ◄──────── get_context(question) (RagService)
```

1. `Indexer` がリポジトリのソースコードを取得し, メタデータ (ファイルパス) を保持した状態でチャンク化します.
2. `VectorStore` が埋め込みベクトルを生成し, ローカルデータベース (既定は `./.chroma_db`) に永続化します.
3. `RagService.get_context` が, 質問に関連するチャンクを取得して返します. 取得したコードは, `code-chat` が, 質問に付加して Gemini に送ります (`--rag`).

このパッケージは, `code-chat-lib` (ロガー, Gemini API のリトライ) に依存します. `code-chat-cli` には依存しません.

---

## 開発・テスト

このパッケージのテストを実行します (リポジトリのルートで実行します).

```bash
uv run pytest --no-cov tests/code_chat_rag
```
