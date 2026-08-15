# Minimal makefile for Sphinx documentation
#

# You can set these variables from the command line, and also
# from the environment for the first two.
SPHINXOPTS    ?=
SPHINXBUILD   ?= uv run sphinx-build
SOURCEDIR     = .
BUILDDIR      = _build

# Put it first so that "make" without argument is like "make help".
help:
	@$(SPHINXBUILD) -M help "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

.PHONY: help Makefile

# Catch-all target: route all unknown targets to Sphinx using the new
# "make mode" option.  $(O) is meant as a shortcut for $(SPHINXOPTS).
%: Makefile
	@$(SPHINXBUILD) -M $@ "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

# apidoc と html ビルドを一括実行するターゲット
.PHONY: apidoc
apidoc:
	uv run sphinx-apidoc -f -o api/code_chat_cli ../packages/code-chat-cli/src/code_chat_cli
	uv run sphinx-apidoc -f -o api/code_chat_rag ../packages/code-chat-rag/src/code_chat_rag
	@$(SPHINXBUILD) -M html "." "$(BUILDDIR)" $(SPHINXOPTS) $(O)
