"""`code_chat_cli.prompts` モジュールのテスト."""

import pytest
from code_chat_cli.prompts import Prompts


class TestPrompts:
    """`Prompts` のテスト."""

    @pytest.mark.parametrize(
        ("template", "placeholder"),
        [
            (Prompts.COMMIT_PROMPT_TEMPLATE_JA, "diff"),
            (Prompts.COMMIT_PROMPT_TEMPLATE_EN, "diff"),
            (Prompts.REVIEW_PROMPT_TEMPLATE, "code"),
        ],
    )
    def test_prompts_template_success(self, template, placeholder):
        """プロンプトテンプレートが, 差し込み用のプレースホルダーを 1 つだけ持ち, `format` で展開できるか検証."""
        rendered = template.format(**{placeholder: "SAMPLE"})

        assert "SAMPLE" in rendered
        assert "{" not in rendered

    def test_prompts_system_instruction_success(self):
        """システム指示が, 空でない文字列として定義されているか検証."""
        assert Prompts.DEFAULT_SYSTEM_INSTRUCTION.strip()
        assert Prompts.WRITE_MODE_SYSTEM_INSTRUCTION.strip()
        assert (
            Prompts.DEFAULT_SYSTEM_INSTRUCTION != Prompts.WRITE_MODE_SYSTEM_INSTRUCTION
        )
