# pylint: disable=protected-access
"""`code_chat_cli.context_cache` モジュールのテスト."""

import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from google.genai.errors import APIError, ClientError

from code_chat_cli.cache_error import CacheError
from code_chat_cli.context_cache import ContextCache
from code_chat_cli.prompts import Prompts


def _cache(name="abc", display_name=None, **overrides):
    """テスト用の CachedContent 相当のオブジェクトを作成する."""
    values = {
        "name": f"cachedContents/{name}",
        "display_name": display_name
        if display_name is not None
        else f"{ContextCache.DISPLAY_PREFIX}/work/{name}",
        "model": "models/gemini-flash-latest",
        "usage_metadata": SimpleNamespace(total_token_count=2048),
        "expire_time": datetime.datetime(2026, 1, 1, 12, 0, tzinfo=datetime.UTC),
        "create_time": datetime.datetime(2026, 1, 1, 11, 0, tzinfo=datetime.UTC),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _client(caches=()):
    """`caches.list` が指定のキャッシュを返す Gemini Client のモックを作成する."""
    client = MagicMock()
    client.caches.list.return_value = list(caches)
    return client


@pytest.fixture
def target_dir(tmp_path):
    """キャッシュ対象のコンテキストとして読み込めるファイルを持つディレクトリ."""
    (tmp_path / "main.py").write_text("print('hello')", encoding="utf-8")
    return tmp_path


class TestDisplayName:
    """`ContextCache._display_name` のテスト."""

    def test_display_name_success(self):
        """対象パスの絶対パスに, このツールを示す接頭辞が付くか検証."""
        assert ContextCache._display_name("src") == f"code-chat:{Path('src').resolve()}"


class TestNormalizeCacheName:
    """`ContextCache._normalize_cache_name` のテスト."""

    @pytest.mark.parametrize(
        ("cache_id", "expected"),
        [
            ("abc123", "cachedContents/abc123"),
            ("cachedContents/abc123", "cachedContents/abc123"),
        ],
    )
    def test_normalize_cache_name_success(self, cache_id, expected):
        """ID のみでも, `cachedContents/` 付きでも, 同じ形式に正規化されるか検証."""
        assert ContextCache._normalize_cache_name(cache_id) == expected


class TestListCodeChatCaches:
    """`ContextCache._list_code_chat_caches` のテスト."""

    def test_list_code_chat_caches_success(self):
        """このツールで作成したキャッシュだけが返るか検証 (display_name が無いものも除外)."""
        mine = _cache("mine")
        client = _client(
            [
                mine,
                _cache("other", display_name="other-app"),
                _cache("none", display_name=""),
            ]
        )
        client.caches.list.return_value[2].display_name = None

        assert ContextCache(client)._list_code_chat_caches() == [mine]

    def test_list_code_chat_caches_retry_exception(self):
        """一覧の取得で一時的なエラー (503) が発生した場合は, リトライされるか検証."""
        mine = _cache("mine")
        client = _client()
        client.caches.list.side_effect = [
            APIError(503, {"error": {"message": "high demand"}}),
            [mine],
        ]

        assert ContextCache(client)._list_code_chat_caches() == [mine]
        assert client.caches.list.call_count == 2


class TestPrintCache:
    """`ContextCache._print_cache` のテスト."""

    def test_print_cache_success(self, capsys):
        """ID・対象・モデル・トークン数・有効期限が表示されるか検証."""
        ContextCache._print_cache(
            _cache("abc", display_name=f"{ContextCache.DISPLAY_PREFIX}/work/src")
        )

        out = capsys.readouterr().out
        assert "cachedContents/abc" in out
        assert "対象: /work/src" in out
        assert "モデル: models/gemini-flash-latest" in out
        assert "トークン数: 2048" in out
        assert "2026-01-01 12:00:00+00:00" in out

    def test_print_cache_without_usage_metadata(self, capsys):
        """トークン数を取得できない場合は, `-` が表示されるか検証."""
        ContextCache._print_cache(_cache(usage_metadata=None))

        assert "トークン数: -" in capsys.readouterr().out


class TestCreateCache:
    """`ContextCache._create_cache` のテスト."""

    def test_create_cache_success(self, target_dir):
        """コンテキスト・システム指示・TTL・display_name を指定してキャッシュが作成されるか検証."""
        client = _client()

        result = ContextCache(client)._create_cache(
            "gemini-flash-latest", str(target_dir), 60
        )

        assert result is client.caches.create.return_value
        kwargs = client.caches.create.call_args.kwargs
        assert kwargs["model"] == "gemini-flash-latest"
        config = kwargs["config"]
        assert config.display_name == ContextCache._display_name(str(target_dir))
        assert config.system_instruction == Prompts.DEFAULT_SYSTEM_INSTRUCTION
        assert config.ttl == "60s"
        assert "print('hello')" in config.contents[0]

    def test_create_cache_empty_directory_failure(self, tmp_path):
        """キャッシュ対象のファイルが無い場合は, API を呼ばずに CacheError が発生するか検証."""
        client = _client()
        empty = tmp_path / "empty"
        empty.mkdir()

        with pytest.raises(CacheError, match="キャッシュ対象のファイルがありません"):
            ContextCache(client)._create_cache("m", str(empty), 60)

        client.caches.create.assert_not_called()

    def test_create_cache_api_error_failure(self, target_dir):
        """API がエラーを返した場合は, 原因を示す CacheError に変換されるか検証."""
        client = _client()
        client.caches.create.side_effect = ClientError(
            429,
            {"error": {"message": "TotalCachedContentStorageTokensPerModelFreeTier"}},
        )

        with pytest.raises(CacheError, match="無料枠"):
            ContextCache(client)._create_cache("m", str(target_dir), 60)

    def test_create_cache_retry_exception(self, target_dir):
        """作成で一時的なエラー (503) が発生した場合は, リトライされて作成されるか検証."""
        client = _client()
        created = _cache("created")
        client.caches.create.side_effect = [
            APIError(503, {"error": {"message": "high demand"}}),
            created,
        ]

        assert ContextCache(client)._create_cache("m", str(target_dir), 60) is created
        assert client.caches.create.call_count == 2


class TestCreate:
    """`ContextCache.create` のテスト."""

    def test_create_success(self, target_dir, capsys):
        """キャッシュが作成され, 作成したキャッシュの情報が表示されるか検証."""
        client = _client()
        client.caches.create.return_value = _cache("created")

        ContextCache(client).create("gemini-flash-latest", str(target_dir), ttl=120)

        assert client.caches.create.call_args.kwargs["config"].ttl == "120s"
        out = capsys.readouterr().out
        assert "キャッシュを作成しました" in out
        assert "cachedContents/created" in out

    def test_create_failure(self, tmp_path):
        """キャッシュ対象が無い場合は, CacheError がそのまま送出されるか検証."""
        empty = tmp_path / "empty"
        empty.mkdir()

        with pytest.raises(CacheError):
            ContextCache(_client()).create("m", str(empty))


class TestUpdate:
    """`ContextCache.update` のテスト."""

    def test_update_success(self, target_dir, capsys):
        """同じ対象の既存キャッシュが, 新規作成のあとに削除されるか検証 (他の対象は残る)."""
        old = _cache("old", display_name=ContextCache._display_name(str(target_dir)))
        other = _cache("other", display_name=f"{ContextCache.DISPLAY_PREFIX}/elsewhere")
        client = _client([old, other])
        client.caches.create.return_value = _cache("new")

        ContextCache(client).update("m", str(target_dir))

        client.caches.delete.assert_called_once_with(name="cachedContents/old")
        out = capsys.readouterr().out
        assert "古いキャッシュを削除しました: cachedContents/old" in out
        assert "キャッシュを更新しました" in out
        assert "cachedContents/new" in out

    def test_update_ttl_success(self, target_dir):
        """指定した保持時間 (省略時は 3600 秒) で, キャッシュが再作成されるか検証."""
        client = _client()
        client.caches.create.return_value = _cache("new")

        ContextCache(client).update("m", str(target_dir))
        ContextCache(client).update("m", str(target_dir), 120)

        ttls = [c.kwargs["config"].ttl for c in client.caches.create.call_args_list]
        assert ttls == ["3600s", "120s"]

    def test_update_create_failure(self, target_dir):
        """再作成に失敗した場合は, 既存のキャッシュを削除せずに CacheError が送出されるか検証."""
        old = _cache("old", display_name=ContextCache._display_name(str(target_dir)))
        client = _client([old])
        client.caches.create.side_effect = ClientError(
            400, {"error": {"message": "too small"}}
        )

        with pytest.raises(CacheError):
            ContextCache(client).update("m", str(target_dir))

        client.caches.delete.assert_not_called()

    def test_update_no_existing(self, target_dir, caplog):
        """既存のキャッシュが無い場合は, 警告を出して新規に作成するか検証."""
        client = _client()
        client.caches.create.return_value = _cache("new")

        ContextCache(client).update("m", str(target_dir))

        client.caches.create.assert_called_once()
        client.caches.delete.assert_not_called()
        assert "新規に作成します" in caplog.text


class TestRemove:
    """`ContextCache.remove` のテスト."""

    def test_remove_target_success(self, capsys):
        """指定した ID のキャッシュが (ID のみの指定でも) 削除されるか検証."""
        client = _client()

        ContextCache(client).remove("abc")

        client.caches.delete.assert_called_once_with(name="cachedContents/abc")
        assert "キャッシュを削除しました: cachedContents/abc" in capsys.readouterr().out

    def test_remove_all_success(self, capsys):
        """ID の省略時は, このツールで作成した全てのキャッシュだけが削除されるか検証."""
        client = _client(
            [_cache("a"), _cache("b"), _cache("x", display_name="other-app")]
        )

        ContextCache(client).remove()

        deleted = [c.kwargs["name"] for c in client.caches.delete.call_args_list]
        assert deleted == ["cachedContents/a", "cachedContents/b"]
        out = capsys.readouterr().out
        assert "キャッシュを削除しました: cachedContents/a" in out
        assert "キャッシュを削除しました: cachedContents/b" in out

    def test_remove_retry_exception(self):
        """削除で一時的なエラー (503) が発生した場合は, リトライされるか検証."""
        client = _client()
        client.caches.delete.side_effect = [
            APIError(503, {"error": {"message": "high demand"}}),
            None,
        ]

        ContextCache(client).remove("abc")

        assert client.caches.delete.call_count == 2

    def test_remove_no_caches(self, capsys):
        """削除対象が無い場合は, 何も削除せずに通知するか検証."""
        client = _client()

        ContextCache(client).remove()

        client.caches.delete.assert_not_called()
        assert "削除対象のキャッシュはありません" in capsys.readouterr().out


class TestListCaches:
    """`ContextCache.list_caches` のテスト."""

    def test_list_caches_success(self, capsys):
        """このツールで作成したキャッシュの一覧が表示されるか検証."""
        client = _client([_cache("a"), _cache("x", display_name="other-app")])

        ContextCache(client).list_caches()

        out = capsys.readouterr().out
        assert "cachedContents/a" in out
        assert "cachedContents/x" not in out

    def test_list_caches_empty(self, capsys):
        """キャッシュが無い場合は, その旨が表示されるか検証."""
        ContextCache(_client()).list_caches()

        assert "アクティブなキャッシュはありません" in capsys.readouterr().out


class TestResolve:
    """`ContextCache.resolve` のテスト."""

    def test_resolve_id_success(self):
        """キャッシュ ID の指定時は, そのキャッシュが取得されるか検証."""
        client = _client()

        result = ContextCache(client).resolve("abc")

        assert result is client.caches.get.return_value
        client.caches.get.assert_called_once_with(name="cachedContents/abc")

    def test_resolve_latest_success(self):
        """ID の省略時は, このツールで作成した最新 (create_time が最大) のキャッシュが選ばれるか検証."""
        older = _cache(
            "older", create_time=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
        )
        newer = _cache(
            "newer", create_time=datetime.datetime(2026, 1, 2, tzinfo=datetime.UTC)
        )
        other = _cache(
            "x",
            display_name="other-app",
            create_time=datetime.datetime(2026, 2, 1, tzinfo=datetime.UTC),
        )

        assert ContextCache(_client([older, newer, other])).resolve(True) is newer

    def test_resolve_latest_ignores_missing_create_time(self):
        """作成日時を取得できないキャッシュがあっても, 比較で例外にならず, 日時のあるものが選ばれるか検証."""
        unknown = _cache("unknown", create_time=None)
        known = _cache(
            "known", create_time=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
        )

        assert ContextCache(_client([unknown, known])).resolve(True) is known

    def test_resolve_no_caches_failure(self):
        """使えるキャッシュが無い場合は, 作成方法を示す CacheError が発生するか検証."""
        with pytest.raises(CacheError, match="cache create"):
            ContextCache(_client()).resolve(True)

    def test_resolve_get_error_failure(self):
        """指定した ID のキャッシュを取得できない場合は, CacheError が発生するか検証."""
        client = _client()
        client.caches.get.side_effect = ClientError(
            404, {"error": {"message": "not found"}}
        )

        with pytest.raises(CacheError, match="取得できませんでした"):
            ContextCache(client).resolve("missing")

    def test_resolve_retry_exception(self):
        """取得で一時的なエラー (503) が発生した場合は, リトライされるか検証."""
        client = _client()
        client.caches.get.side_effect = [
            APIError(503, {"error": {"message": "high demand"}}),
            "cache",
        ]

        assert ContextCache(client).resolve("abc") == "cache"
        assert client.caches.get.call_count == 2
