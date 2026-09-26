# code-chat-lib

`code-chat-lib` は, `code-chat-cli` / `code-chat-rag` / `code-chat-mcp` から共通で使う, 小さなライブラリです.

## 主なコンポーネント

* **`logger`**: ログの設定 (`setup_logging`, `set_trace`), ロガーの取得 (`get_logger`), 例外のログ出力 (`log_exception`).
* **`api`**: Gemini API の呼び出しのリトライ (`call_with_retry`, `stream_with_retry` など). リトライの方針は, ここに集約します.
* **`gemini_error` / `gemini_error_kind`**: Gemini API のエラー (`APIError`) から, 概要とヒントを作成します.
* **`retry_policy`**: リトライの設定値 (試行回数, 待ち時間).

このパッケージは, 他の `code-chat-*` パッケージに依存しません.
