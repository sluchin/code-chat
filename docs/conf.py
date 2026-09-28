# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# Project information
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

import os
import sys

project = "code-chat"
copyright = "2026, Tetsuya Higashi"
author = "Tetsuya Higashi"

# General configuration
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

# ソースコードの存在するディレクトリをパスに追加 (docs/ から見た相対パス)
sys.path.insert(0, os.path.abspath("../packages/code-chat-cli/src"))
sys.path.insert(0, os.path.abspath("../packages/code-chat-rag/src"))
sys.path.insert(0, os.path.abspath("../packages/code-chat-mcp/src"))

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",  # Google スタイル Docstring の解釈に必須
    "sphinx.ext.viewcode",  # ソースコードへのリンクを表示（任意）
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

language = "ja"

# Options for HTML output
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

# html_theme = 'alabaster'
# html_theme = "furo"
# テーマの変更
html_theme = "pydata_sphinx_theme"

# テーマ固有のオプション設定（例：ダークモード対応やソーシャルリンクなど）
html_theme_options = {
    "use_edit_page_button": True,  # GitHubの編集ボタンを表示
    "show_toc_level": 2,  # 目次の深さ
}
html_static_path = ["_static"]

# use_edit_page_button に必須 (GitHub の編集ボタンのリンク先を構成する)
html_context = {
    "github_user": "sluchin",
    "github_repo": "code-chat",
    "github_version": "main",
    "doc_path": "docs",
}
