# TODO (開発ロードマップ)

`code-chat` の今後の機能追加および改善タスクの一覧です。

---

## 📌 継続改善・バックログ (必要に応じて対応)

- [ ] **エラーハンドリングと安定性向上**
  - [ ] API エラー（レートリミット、接続不可など）時の適切なリトライおよびユーザー通知
  - [ ] `is_partial_code` 誤検知の継続的な監視とパターン調整
- [ ] **OAuth のスコープを最小限にする (`auth.py`)**
  - 現状の `SCOPES` は、`cloud-platform` (Google Cloud 全体への広い権限) と `generative-language.retriever` の 2 つ。`cloud-platform` は、トークンが漏れた場合の影響が大きく、同意画面にも広い権限の要求が表示される
  - [ ] `cloud-platform` を外し、`generative-language` 系のスコープだけで、次の動作を確認する (実際の OAuth ログインが必要で、モックでは確認できない)
    - 通常のチャット (`code-chat --oauth "こんにちは"`) とストリーミング / `--list-models` / `--review` / `--generate-commit-msg` / `--mcp` (Function Calling)
  - [ ] 動作した場合は、`SCOPES` を変更し、`OAUTH.md` の 3-5 (スコープの表) と `tests/code_chat_cli/test_auth.py` を更新する。保存済みのトークンは古いスコープのままなので、`code-chat --login` で再ログインが必要な旨を、`OAUTH.md` に書く
  - [ ] 動かなかった場合は、必要なスコープと理由を `OAUTH.md` に記録する

---

## 🔍 中期タスク (v0.3.0 - コンテキスト拡張 & LLM対応)

- [ ] **RAG（検索拡張生成）対応**
  - [ ] ソースコードおよびドキュメントのインデックス化 / 埋め込み（Embedding）生成処理の実装
  - [ ] ベクトルデータベース（Chroma, Qdrant, LanceDB 等のローカル軽量DB）の選定・組み込み
  - [ ] ユーザーの質問・変更指示に関連するファイル・コードブロックの動的フィルタリング抽出
- [ ] **マルチ LLM プロバイダー対応 (Ollama / Claude 等)**
  - [ ] ローカル LLM (Ollama) バックエンドの抽象化クラス・接続インターフェース実装
  - [ ] 設定ファイル (`~/.config/code-chat/config.toml` 等) による利用モデルの切り替え

---

## 🌐 長期タスク (v0.4.0 - UI/UX & 国際化)

- [ ] **多言語化対応 (i18n)**
  - [ ] システムプロンプトおよび出力フォーマットの言語切り替え（日本語 / 英語）
  - [ ] CLI 表示メッセージ・エラーログの多言語リソース化
  - [ ] 環境変数 (`LANG`) や設定ファイルによる言語指定サポート
- [ ] **CLI UX の洗練**
  - [ ] 対話モードでのコード差分（Diff）ハイライト表示 (`rich` ライブラリ連携)
  - [ ] ファイル書き込み前の対話的インタラクティブ Diff 表示 (Apply / Reject / Edit)
