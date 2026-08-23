"""プロンプトテンプレートおよびシステム指示の定義."""

COMMIT_PROMPT_TEMPLATE_JA = """\
以下の git diff の内容を分析し, 適切な Git コミットメッセージを作成してください.

【制約事項】
- 1行目は変更内容を簡潔に要約したタイトル（50文字程度）にしてください.
- 必要に応じて空行を挟み, 箇条書きで変更理由や詳細を記述してください.
- プレフィックス（feat:, fix:, docs:, refactor:, test: など）を使用してください.
- 記述は日本語で行ってください.
- 余計な解説やコードブロックの枠（``` など）は含めず, コミットメッセージ本文のみを出力してください.

【git diff】
{diff}
"""

COMMIT_PROMPT_TEMPLATE_EN = """\
Analyze the following git diff and generate a concise, professional Git commit message in English.

[Constraints]
- Follow Conventional Commits format (e.g., feat:, fix:, docs:, refactor:, test:, chore:).
- Line 1: Summary title written in the imperative mood (e.g., "add feature" instead of "added feature"), within 50 characters.
- Leave one blank line, followed by bullet points explaining the changes and reasons if necessary.
- Output ONLY the commit message body. Do NOT wrap it in code blocks (```) or include any extra conversational text.

[git diff]
{diff}
"""

WRITE_MODE_SYSTEM_INSTRUCTION = """
あなたはコード自動生成アシスタントです.
指定されたファイルを完全に置き換えるための実行可能なコードのみを出力してください.

【厳格な遵守事項】
1. Markdown のコードブロック記号（```python や ```）を含めないでください.
2. 挨拶, 解説, 説明文, 前置き, 後書きは一切含めないでください.
3. 出力の1文字目から最後の文字まで, すべてPythonソースコードとして直接実行可能なテキストのみを出力してください.
"""

REVIEW_PROMPT_TEMPLATE = """\
あなたはプロのソフトウェアエンジニアです. 以下のコード差分（diff）またはファイル内容を詳細にレビューしてください.

### レビュー観点
1. **潜在的なバグ・不具合**: ヌルポインタ, エッジケースの考慮漏れ, リソースリークなど
2. **パフォーマンス・効率性**: 不要なループや不必要な処理
3. **コード品質・可読性**: 命名規則, 複雑度の高い処理の簡略化
4. **セキュリティ**: 脆弱性や安全でない実装

### レビュー対象
{code}
"""
