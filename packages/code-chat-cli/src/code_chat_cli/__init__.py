"""Gemini API CLI Package."""

# エントリポイントは `code_chat_cli.chat:main`. ここで chat を import すると, code_chat_rag が
# code_chat_cli.logger を import した際に循環 import になるため, 何も import しない.
__version__ = "0.1.0"
__all__ = ["__version__"]
