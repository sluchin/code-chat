# code-chat-rag

`code-chat-rag` は, ローカルコードベースに対する RAG (Retrieval-Augmented Generation) パイプラインを提供するコアパッケージです. コードのドキュメント化・チャンク化・ベクター検索・LLM を用いた回答生成のロジックを集約しています.

---

## 主なコンポーネント

* **`CodeIndexer`**: リポジトリ構造を解析し, ソースコードを適切なサイズの Document チャンクに分割します.
* **`VectorStore`**: ChromaDB を使用し, 分割されたコードチャンクの埋め込み (Embedding) および類似度検索を管理します.
* **`CodeRagService`**: インデックス作成から LCEL (LangChain Expression Language) チェーンの構築・実行までを統括する高レベルサービスインターフェースです.

---

## 使い方

### 1. リポジトリのインデックスを作成する

指定したディレクトリ配下のソースコードをロードし, ChromaDB に保存します.

```python
from code_chat_rag import CodeRagService

service = CodeRagService(persist_directory="./.chroma_db")
chunk_count = service.index_repository("/path/to/target/repo")

print(f"Indexed {chunk_count} chunks successfully.")

```

---

### 2. 回答のストリーミング取得 (`ask_stream`)

インデックスを参照してクエリに回答します. トークン単位でリアルタイムにストリーミング処理を行うため, CLI や Web UI でのリアルタイム表示に適しています.

```python
from code_chat_rag import CodeRagService

service = CodeRagService(persist_directory="./.chroma_db")

query = "ChromaDB への接続処理を行っているモジュールはどれですか？"
for token in service.ask_stream(query):
    print(token, end="", flush=True)
print()

```

---

### 3. 一括回答取得 (`ask`)

一括でレスポンス文字列を取得する場合に使用します.

```python
answer = service.ask("認証処理のロジックについて解説してください.")
print(answer)

```

---

## アーキテクチャ概要

```text
[ Source Code ] 
       │
       ▼  (CodeIndexer)
[ Document Chunks ]
       │
       ▼  (VectorStore / ChromaDB)
[ Vector Index ] ──► (Retriever) ──┐
                                   ├──► [ LCEL Chain ] ──► [ LLM Response ]
[ User Query ] ────────────────────┘

```

1. `CodeIndexer` がリポジトリのソースコードを取得し, メタデータ (ファイルパス等) を保持した状態でチャンク化します.
2. `VectorStore` が埋め込みベクトルを生成し, ローカルデータベース (`./.chroma_db`) に永続化します.
3. `CodeRagService` が関連コードのコンテキスト抽出とプロンプト構築を行い, Google Gemini API 経由で回答を生成します.

---

## 開発・テスト

パッケージ単体でのテスト実行:

```bash
uv run pytest

```
