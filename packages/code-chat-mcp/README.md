# code-chat-mcp

`code-chat-mcp` は、**Model Context Protocol (MCP)** を利用して Gemini API と各種外部ツール（ファイルシステム、Git、データベース、各種APIなど）を連携させるためのパッケージです。

Model Context Protocol を採用することで、Gemini が必要に応じて外部ツールを自律的に呼び出し（Function Calling / Tool Use）、実行結果を取り込んで応答できるようにします。

---

## 概要

- **標準 MCP サーバーとの連携**: 市販・コミュニティ作成の MCP サーバー（Stdio 形式等）と接続
- **ツール自動呼び出し (Tool Call Loop)**: Gemini API からのツール実行リクエストを受け取り、ローカルや外部サービス上で安全に実行・結果返却
- **設定ファイル駆動**: `mcp_config.json` 等で利用可能な MCP サーバーを柔軟に構成可能
- **CLI パッケージとの統合**: `code-chat-cli` から `--mcp` オプションや `/mcp` コマンド経由で呼び出し可能

---

## インストール

単体パッケージとしてインストールするか、プロジェクトのワークスペース（uv / poetry 等）から導入します。

```bash
# パッケージディレクトリ内でのインストール例
pip install -e packages/code-chat-mcp

```

---

## 設定ファイル (`mcp_config.json`)

接続したい MCP サーバー情報を JSON 形式で記述します。デフォルトでは実行ディレクトリ直下または環境変数で指定されたパスを参照します。

### 設定例

```json
{
  "mcpServers": {
    "git": {
      "command": "uvx",
      "args": [
        "mcp-server-git",
        "--repository",
        "."
      ]
    },
    "fetch": {
      "command": "uvx",
      "args": [
        "mcp-server-fetch"
      ]
    }
  }
}

```

---

## 主なモジュールと設計

| モジュール | 役割 |
| --- | --- |
| `mcp_service.py` | MCP クライアントの初期化、サーバー接続管理、ライフサイクル制御 |
| `runner.py` | プロンプトの受信、Gemini API へのツール定義注入、Tool Call ループの制御 |
| `config.py` | `mcp_config.json` のロードおよび検証 |
| `tools.py` | MCP ツールを Gemini API が理解できる Function Declaration 形式に変換 |

---

## 使い方 (Python API)

Python コードから直接 MCP サービスを呼び出す場合の使用例です。

```python
import asyncio
from code_chat_mcp.mcp_service import handle_mcp_run


async def main():
    prompt = "現在の Git リポジトリのステータスを確認し、未コミットの変更を要約してください。"
    config_path = "mcp_config.json"

    # MCP サーバーとの接続・ツール呼び出し・結果取得を一括実行
    result = await handle_mcp_run(user_prompt=prompt, config_path=config_path)
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
```

---

## CLI からの使用方法 (`code-chat-cli`)

`code-chat-cli` 側から本パッケージを利用する主なコマンドです。

```bash
# MCP 設定やサーバー接続確認
code-chat mcp status
code-chat mcp test

# ワンショットでの MCP 実行
code-chat --mcp -p "git status を確認して変更点を教えて"

# 対話型モード内での実行
You > /mcp 最近のコミットログを3件取得してください

```

---

## 注意事項

* **安全性の確保**: MCP サーバー経由でのファイル書き込みやコマンド実行を行う際は、事前に動作対象のパスや権限を確認してください。
* **Gemini Function Calling Limits**: 登録する MCP サーバーのツール数が極端に多い場合、プロンプトのトークン消費が増加する可能性があります。必要なサーバーのみ設定ファイルに記述することを推奨します。
