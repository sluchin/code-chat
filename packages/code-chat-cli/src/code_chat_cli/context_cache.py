"""Gemini の Context Caching (明示的キャッシュ) の作成・更新・削除・一覧・解決を行うモジュール.

このツールで作成したキャッシュは, `display_name` の先頭に `code-chat:` を付けて識別します.
他のアプリケーションで作成したキャッシュは, 一覧・削除・自動選択の対象になりません.

キャッシュには, システム指示を含めてコンテキストを保存します. キャッシュを使ったリクエストでは,
`system_instruction` を別途指定できないため, 使用するモデルもキャッシュ作成時のものに固定されます.
"""

from pathlib import Path
from typing import Any

from google.genai import types
from google.genai.errors import APIError

from code_chat_cli.cache_error import CacheError
from code_chat_cli.file_utils import read_path_content
from code_chat_cli.logger import get_logger
from code_chat_cli.prompts import Prompts

logger = get_logger(__name__)


class ContextCache:
    """Gemini の Context Caching (明示的キャッシュ) を管理するクラス.

    Attributes:
        client: Gemini Client インスタンス.

    """

    DISPLAY_PREFIX = "code-chat:"
    """このツールで作成したキャッシュを識別する display_name の接頭辞."""

    _NAME_PREFIX = "cachedContents/"

    def __init__(self, client: Any) -> None:
        """ContextCache インスタンスを初期化します.

        Args:
            client (Any): Gemini Client インスタンス.

        """
        self.client = client

    def create(self, model: str, target: str = ".", ttl: int = 3600) -> None:
        """対象パスのコンテキストから新規キャッシュを作成し, 結果を表示します.

        Args:
            model (str): キャッシュを使用するモデル名 (キャッシュはこのモデルに紐づく).
            target (str): コンテキストとして読み込むファイル・ディレクトリのパス. Defaults to ".".
            ttl (int): キャッシュの保持時間 (秒). Defaults to 3600.

        Raises:
            CacheError: キャッシュを作成できなかった場合.

        """
        cache = self._create_cache(model, target, ttl)
        logger.info("キャッシュを作成しました")
        self._print_cache(cache)

    def update(self, model: str, target: str = ".") -> None:
        """同じ対象パスの既存キャッシュを削除し, 最新の内容で作り直します.

        キャッシュの内容は更新できないため, 削除して再作成します. 既存のキャッシュがない場合は,
        新規に作成します. 保持時間は既定値 (3600 秒) になります.

        Args:
            model (str): キャッシュを使用するモデル名.
            target (str): コンテキストとして読み込むファイル・ディレクトリのパス. Defaults to ".".

        Raises:
            CacheError: キャッシュを作成できなかった場合.

        """
        display_name = self._display_name(target)
        existing = [
            c for c in self._list_code_chat_caches() if c.display_name == display_name
        ]
        if not existing:
            logger.warning(
                "既存のキャッシュが見つからないため, 新規に作成します: %s", target
            )

        # 新しい内容を読み込めることを確認してから, 既存のキャッシュを削除する
        cache = self._create_cache(model, target, 3600)
        for old in existing:
            self.client.caches.delete(name=old.name)
            logger.info("古いキャッシュを削除しました: %s", old.name)

        logger.info("キャッシュを更新しました")
        self._print_cache(cache)

    def remove(self, target: str | None = None) -> None:
        """指定したキャッシュ (省略時は, このツールで作成した全て) を削除します.

        Args:
            target (str | None): キャッシュ ID (`cachedContents/<ID>` または `<ID>`). Defaults to None.

        """
        if target:
            name = self._normalize_cache_name(target)
            self.client.caches.delete(name=name)
            logger.info("キャッシュを削除しました: %s", name)
            return

        caches = self._list_code_chat_caches()
        if not caches:
            logger.info("削除対象のキャッシュはありません")
            return
        for cache in caches:
            self.client.caches.delete(name=cache.name)
            logger.info("キャッシュを削除しました: %s", cache.name)

    def list_caches(self) -> None:
        """このツールで作成したキャッシュの一覧を表示します."""
        caches = self._list_code_chat_caches()
        if not caches:
            print("アクティブなキャッシュはありません")
            return

        print("アクティブなキャッシュ一覧:")
        for cache in caches:
            self._print_cache(cache)

    def resolve(self, cache: bool | str) -> Any:
        """`-c` / `--cache` の指定から, 使用するキャッシュを取得します.

        Args:
            cache (bool | str): True の場合は最新のキャッシュを自動選択, 文字列の場合はそのキャッシュ ID.

        Returns:
            Any: 使用する CachedContent.

        Raises:
            CacheError: キャッシュが見つからない場合.

        """
        if isinstance(cache, str):
            try:
                return self.client.caches.get(name=self._normalize_cache_name(cache))
            except APIError as e:
                raise CacheError(
                    f"キャッシュ '{cache}' を取得できませんでした: {e}"
                ) from e

        caches = self._list_code_chat_caches()
        if not caches:
            raise CacheError(
                "使用できるキャッシュがありません. code-chat cache create で作成してください"
            )
        return max(caches, key=lambda c: c.create_time)

    @staticmethod
    def _display_name(target: str) -> str:
        """対象パスから, このツールで作成したキャッシュを識別する display_name を作成します."""
        return f"{ContextCache.DISPLAY_PREFIX}{Path(target).resolve()}"

    @staticmethod
    def _normalize_cache_name(cache_id: str) -> str:
        """キャッシュ ID を `cachedContents/<ID>` の形式に正規化します."""
        if cache_id.startswith(ContextCache._NAME_PREFIX):
            return cache_id
        return f"{ContextCache._NAME_PREFIX}{cache_id}"

    @staticmethod
    def _explain_api_error(error: APIError) -> str:
        """キャッシュ API のエラーから, 原因と対処を示すメッセージを作成します."""
        message = str(error)
        if "FreeTier" in message:
            return (
                "無料枠では Context Caching を利用できません "
                "(課金を有効にした有料枠のプロジェクトが必要です)"
            )
        if "too small" in message:
            return "コンテキストが小さすぎます (キャッシュには最小トークン数以上が必要です. 例: 1024)"
        return f"Context Caching の API でエラーが発生しました: {message}"

    @staticmethod
    def _print_cache(cache: Any) -> None:
        """キャッシュ 1 件の情報を標準出力に表示します."""
        tokens = cache.usage_metadata.total_token_count if cache.usage_metadata else "-"
        print(f"  ID: {cache.name}")
        print(
            f"    対象: {(cache.display_name or '')[len(ContextCache.DISPLAY_PREFIX) :]}"
        )
        print(f"    モデル: {cache.model}")
        print(f"    トークン数: {tokens}")
        print(f"    有効期限: {cache.expire_time}")

    def _list_code_chat_caches(self) -> list[Any]:
        """このツールで作成したキャッシュの一覧を返します."""
        return [
            cache
            for cache in self.client.caches.list()
            if (cache.display_name or "").startswith(self.DISPLAY_PREFIX)
        ]

    def _create_cache(self, model: str, target: str, ttl: int) -> Any:
        """対象パスのコンテキストからキャッシュを作成します.

        Raises:
            CacheError: 読み込めるコンテキストがない場合, または API がエラーを返した場合.

        """
        contents = read_path_content(target)
        if not contents:
            raise CacheError(f"'{target}' にキャッシュ対象のファイルがありません")

        try:
            return self.client.caches.create(
                model=model,
                config=types.CreateCachedContentConfig(
                    display_name=self._display_name(target),
                    system_instruction=Prompts.DEFAULT_SYSTEM_INSTRUCTION,
                    contents=[contents],
                    ttl=f"{ttl}s",
                ),
            )
        except APIError as e:
            raise CacheError(self._explain_api_error(e)) from e
