.. code-chat documentation master file, created by
   sphinx-quickstart on Wed Aug 12 20:00:25 2026.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

code-chat documentation
=======================

``code-chat`` は, Gemini を使った対話・コード修正・コードレビュー・コミットメッセージ生成に,
RAG (コードベース検索) と MCP (ツール連携) を組み合わせた開発者向け CLI ツールです.

以下は各パッケージの API リファレンスです. 使い方やコマンド仕様は, リポジトリの
``README.md`` と ``COMMANDS.md``, OAuth ログインの設定手順は ``OAUTH.md`` を参照してください.


.. toctree::
   :maxdepth: 2
   :caption: Contents:

   api/code_chat_cli/modules
   api/code_chat_rag/modules
   api/code_chat_mcp/modules
