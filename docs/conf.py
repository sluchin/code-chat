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

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
