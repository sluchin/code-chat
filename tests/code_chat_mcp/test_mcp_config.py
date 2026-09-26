"""`code_chat_mcp.mcp_config` モジュールのテスト."""

import json
import logging
from pathlib import Path

from code_chat_mcp.mcp_config import McpConfig


def _write_config(path: Path, data: object) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class TestInit:
    """`McpConfig.__init__` のテスト."""

    def test_init_default_path_used_when_not_specified_success(
        self, monkeypatch, tmp_path
    ):
        """パス未指定の場合は ~/.config/code-chat/mcp.json を参照し, 無ければ空になるか検証."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        config = McpConfig()

        assert config.config_path == tmp_path / ".config" / "code-chat" / "mcp.json"
        assert not config.servers


class TestLoadMcpConfig:
    """`McpConfig.load_mcp_config` のテスト."""

    def test_load_mcp_config_success(self, tmp_path):
        """サーバー定義が読み込まれ, 省略項目に既定値が入るか検証."""
        path = _write_config(
            tmp_path / "mcp.json",
            {
                "mcpServers": {
                    "full": {
                        "command": "npx",
                        "args": ["-y", "server"],
                        "env": {"KEY": "value"},
                    },
                    "minimal": {},
                }
            },
        )

        config = McpConfig(path)

        assert set(config.servers) == {"full", "minimal"}
        full = config.servers["full"]
        assert full.name == "full"
        assert full.command == "npx"
        assert full.args == ["-y", "server"]
        assert full.env == {"KEY": "value"}
        assert full.enabled is True
        minimal = config.servers["minimal"]
        assert minimal.command == ""
        assert minimal.args == []
        assert minimal.env == {}

    def test_load_mcp_config_missing_file_failure(self, tmp_path, caplog):
        """設定ファイルが存在しない場合, 警告を出して空の辞書を返すか検証."""
        with caplog.at_level(logging.WARNING):
            config = McpConfig(tmp_path / "missing.json")

        assert not config.servers
        assert "MCP 設定ファイルが見つかりません" in caplog.text

    def test_load_mcp_config_invalid_json_exception(self, tmp_path, caplog):
        """JSON が不正な場合, エラーログを出して空の辞書を返すか検証."""
        path = tmp_path / "mcp.json"
        path.write_text("{ not json", encoding="utf-8")

        with caplog.at_level(logging.ERROR):
            config = McpConfig(path)

        assert not config.servers
        assert "MCP 設定ファイルの読み込みに失敗しました" in caplog.text

    def test_load_mcp_config_disabled_servers_are_skipped(self, tmp_path):
        """enabled / enable が false のサーバーは読み込まれないか検証."""
        path = _write_config(
            tmp_path / "mcp.json",
            {
                "mcpServers": {
                    "off1": {"command": "a", "enabled": False},
                    "off2": {"command": "b", "enable": False},
                    "on": {"command": "c", "enable": True},
                }
            },
        )

        config = McpConfig(path)

        assert list(config.servers) == ["on"]

    def test_load_mcp_config_no_mcp_servers_key(self, tmp_path):
        """mcpServers キーが無い場合は空になるか検証."""
        config = McpConfig(_write_config(tmp_path / "mcp.json", {}))

        assert not config.servers
