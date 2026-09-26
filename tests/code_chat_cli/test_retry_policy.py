"""`code_chat_cli.retry_policy` モジュールのテスト."""

from code_chat_cli.retry_policy import RetryPolicy


class TestRetryPolicy:
    """`RetryPolicy` のテスト."""

    def test_retry_policy_success(self):
        """リトライの設定値が, 有効な範囲 (試行回数は 2 回以上, 待ち時間の上限は初回以上) で定義されているか検証."""
        assert RetryPolicy.MAX_ATTEMPTS >= 2
        assert 0 < RetryPolicy.INITIAL_DELAY <= RetryPolicy.MAX_DELAY
        assert RetryPolicy.EXP_BASE > 1
        assert RetryPolicy.JITTER >= 0
        assert RetryPolicy.RETRY_DELAY_MARGIN >= 0
