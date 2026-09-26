# code-chat-mcp

`code-chat-mcp` は, **Model Context Protocol (MCP)** のサーバーとの接続を扱うパッケージです. 設定ファイルの読み込み, MCP サーバーの起動 (Stdio), ツール一覧の取得, ツールの実行を提供します.

Gemini からのツール呼び出し (Function Calling) と, このパッケージの接続とをつなぐ処理 (ツール呼び出しのループ) は, `code-chat-cli` の `query_handler.py` (`QueryHandler`) と `mcp.py` (`handle_mcp_run`) にあります.

---

## 概要

* **標準 MCP サーバーとの連携**: 市販・コミュニティ作成の MCP サーバー (Stdio 形式) に, 公式の SDK (`mcp`) で接続します.
* **設定ファイル駆動**: `~/.config/code-chat/mcp.json` で, 利用する MCP サーバーを構成します.
* **CLI との統合**: `code-chat` の `--mcp` オプション, 対話モードの `/mcp` コマンド, `mcp status` / `mcp test` サブコマンドから使われます.

---

## 設定ファイル (`mcp.json`)

既定のパスは `~/.config/code-chat/mcp.json` です. ファイルがない場合は, 警告を出して, サーバーなしで動作します.

```json
{
  "mcpServers": {
    "git": {
      "command": "uvx",
      "args": ["mcp-server-git", "--repository", "${CWD}"]
    },
    "fetch": {
      "command": "uvx",
      "args": ["mcp-server-fetch"],
      "env": {"KEY": "value"},
      "enabled": false
    }
  }
}
```

* `command` / `args`: サーバーを起動するコマンドと引数. `args` 内の `${CWD}` は, 実行時のカレントディレクトリの絶対パスに置換されます.
* `env`: サーバーに追加で渡す環境変数 (任意). 親プロセスの環境変数は, `HOME` `LOGNAME` `PATH` `SHELL` `TERM` `USER` だけが引き継がれるため, サーバーが必要とするトークンなどは, ここに書きます.
* `enabled`: `false` でサーバーを無効化します (`enable` でも可. 省略時は有効).

---

## 主なモジュール

| モジュール | 役割 |
| --- | --- |
| `mcp_config.py` (`McpConfig`) | `mcp.json` の読み込み. 無効なサーバーは除く |
| `mcp_server_config.py` (`McpServerConfig`) | サーバー 1 台の設定 (名前, コマンド, 引数, 環境変数, 有効・無効) |
| `mcp_server_connection.py` (`McpServerConnection`) | サーバー 1 台への接続. サブプロセスを起動して, ツール一覧の取得とツールの実行を行う |
| `mcp_service.py` (`McpService`) | 複数のサーバーをまとめて扱う. 全サーバーのツール一覧の取得, ツールの実行, 導通テスト |
| `mcp_tool_info.py` (`McpToolInfo`) | ツール 1 件の情報 (サーバー名, ツール名, 説明, 入力スキーマ) |

ツールの呼び出しごとに, サーバーのサブプロセスを起動し, 終了します (呼び出しの間で, サーバーの状態は保持されません).

---

## 使い方 (Python API)

```python
import asyncio

from code_chat_mcp.mcp_service import McpService


async def main():
    async with McpService() as service:
        # 有効な全サーバーのツール一覧を取得する
        for tool in await service.get_all_tools():
            print(f"{tool.server_name}: {tool.name} - {tool.description}")

        # ツールを実行する
        result = await service.call_tool(
            server_name="git", tool_name="git_status", arguments={"repo_path": "."}
        )
        print(result.content)


asyncio.run(main())
```

サーバーの接続に失敗した場合, `McpServerConnection.get_tools` / `call_tool` は例外を送出します. `McpService.get_all_tools` は, 失敗したサーバーを記録して飛ばし, 他のサーバーのツールを返します.

---

## CLI からの使用方法 (`code-chat`)

```bash
# サーバーごとのツール一覧
code-chat mcp status

# 全サーバーの導通テスト (サーバーごとに [OK] / [NG] を表示)
code-chat mcp test

# MCP のツールを使って, ワンショットで実行する
code-chat "git status を確認して変更点を教えて" --mcp

# ツール呼び出しの回数の上限を変える (既定: 20)
code-chat "git のログを調べて" --mcp --max-tool-rounds 5

# 対話モード内で実行する
# You > /mcp 最近のコミットログを 3 件取得してください
```

---

## 注意事項

* **安全性の確保**: MCP サーバー経由でのファイル書き込みやコマンド実行を行う際は, 事前に, 対象のパスや権限を確認してください.
* **トークンの消費**: 登録するサーバーのツール数が多いと, プロンプトのトークン消費が増えます. 必要なサーバーだけを設定してください.
* **テスト**: リポジトリのルートで `uv run pytest --no-cov tests/code_chat_mcp` を実行します.
