"""プロンプトテンプレートおよびシステム指示の定義モジュール.

コミットメッセージ生成, ファイル自動書き込みモード, コードレビューなどで使用される
システム指示および各種プロンプトテンプレートを提供します.
"""


class Prompts:
    """プロンプトテンプレートおよびシステム指示を保持するクラス."""

    DEFAULT_SYSTEM_INSTRUCTION: str = (
        "あなたは優秀なプログラミングアシスタントです."
        "提供されたソースコードを把握し, "
        "ユーザーからの指示に従って修正案の提示やコード解説, レビューを行ってください."
    )
    """通常の対話で使用するシステム指示 (Context Caching 使用時は, キャッシュ作成時にこの指示を含める)."""

    COMMIT_PROMPT_TEMPLATE: str = """\
Analyze the following git diff and generate a concise, professional Git commit message in English.

[Constraints]
- Follow Conventional Commits format (e.g., feat:, fix:, docs:, refactor:, test:, chore:).
- Line 1: Summary title written in the imperative mood (e.g., "add feature" instead of "added feature"), within 50 characters.
- Leave one blank line, followed by bullet points explaining the changes and reasons if necessary.
- Output ONLY the commit message body. Do NOT wrap it in code blocks (```) or include any extra conversational text.

[git diff]
{diff}
"""
    """コミットメッセージ生成プロンプトテンプレート (英語で出力させる)."""

    WRITE_MODE_SYSTEM_INSTRUCTION: str = """
あなたはコード自動生成アシスタントです.
指定されたファイルを完全に置き換えるための実行可能なコードのみを出力してください.

【厳格な遵守事項】
1. Markdown のコードブロック記号（```python や ```）を含めないでください.
2. 挨拶, 解説, 説明文, 前置き, 後書きは一切含めないでください.
3. 出力の1文字目から最後の文字まで, すべてPythonソースコードとして直接実行可能なテキストのみを出力してください.
"""
    """ファイル直接上書き生成モード（writeモード）用のシステム指示テキスト."""

    REVIEW_PROMPT_TEMPLATE: str = """\
あなたはプロのソフトウェアエンジニアです. 以下のコード差分（diff）またはファイル内容を詳細にレビューしてください.

### レビュー観点
1. **潜在的なバグ・不具合**: ヌルポインタ, エッジケースの考慮漏れ, リソースリークなど
2. **パフォーマンス・効率性**: 不要なループや不必要な処理
3. **コード品質・可読性**: 命名規則, 複雑度の高い処理の簡略化
4. **セキュリティ**: 脆弱性や安全でない実装

### レビュー対象
{code}
"""
    """コードレビュー実行用のプロンプトテンプレート."""
