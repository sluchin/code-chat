"""`code_chat_rag.indexer` モジュールのテスト."""

import subprocess
import sys
from unittest.mock import ANY, MagicMock, patch

import pytest
from langchain_core.documents import Document

from code_chat_rag.indexer import Indexer


class TestIndexer:
    """`Indexer` のテスト."""

    def test_indexer_import_without_cli_success(self):
        """code_chat_cli を先に import しなくても, code_chat_rag を単独で import できるか検証する (循環 import の回帰テスト)."""
        result = subprocess.run(
            [sys.executable, "-c", "import code_chat_rag.indexer"],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr


class TestInit:
    """`Indexer.__init__` のテスト."""

    def test_init_success(self):
        """初期化パラメータが正しく保持されるか検証する."""
        indexer = Indexer(
            input_dirs=["/dummy/repo"],
            suffixes=[".py", ".ts"],
            chunk_size=500,
            chunk_overlap=50,
        )

        assert indexer.input_dirs == ["/dummy/repo"]
        assert indexer.suffixes == [".py", ".ts"]
        assert indexer.chunk_size == 500
        assert indexer.chunk_overlap == 50


class TestLoadAndChunk:
    """`Indexer.load_and_chunk` のテスト."""

    @patch("code_chat_rag.indexer.GenericLoader")
    @patch("code_chat_rag.indexer.RecursiveCharacterTextSplitter")
    def test_load_and_chunk_success(self, mock_splitter_cls, mock_loader_cls, tmp_path):
        """ファイルロードからチャンク分割, 辞書型配列への変換までの一連の流れを検証する."""
        # 実在する一時ディレクトリを準備
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        (repo_dir / "main.py").write_text("def main(): pass\n", encoding="utf-8")

        # モックの作成
        mock_loader = MagicMock()
        mock_loader_cls.from_filesystem.return_value = mock_loader

        # ロードされる LangChain Document のモック
        raw_docs = [
            Document(page_content="def main(): pass", metadata={"source": "main.py"})
        ]
        mock_loader.load.return_value = raw_docs

        # 分割後の Document のモック
        mock_splitter = MagicMock()
        split_docs = [
            Document(
                page_content="def main():", metadata={"source": "main.py", "line": 1}
            ),
            Document(
                page_content="    pass", metadata={"source": "main.py", "line": 2}
            ),
        ]
        mock_splitter.split_documents.return_value = split_docs
        mock_splitter_cls.from_language.return_value = mock_splitter

        # テスト対象の実行
        indexer = Indexer(input_dirs=[str(repo_dir)])
        chunks = indexer.load_and_chunk()

        # 検証
        assert len(chunks) == 2
        assert chunks[0] == {
            "page_content": "def main():",
            "metadata": {"source": "main.py", "line": 1},
        }
        assert chunks[1] == {
            "page_content": "    pass",
            "metadata": {"source": "main.py", "line": 2},
        }

        # ANY を使うことで LanguageParser インスタンスの不一致を回避します
        # ファイル単位で LanguageParser 付きのローダーが生成される
        mock_loader_cls.from_filesystem.assert_called_once_with(
            path=str(repo_dir),
            glob="main.py",
            parser=ANY,
        )
        mock_loader.load.assert_called_once()
        mock_splitter.split_documents.assert_called_once_with(raw_docs)

    def test_load_and_chunk_file_not_found_failure(self):
        """存在しないパスを指定した場合に FileNotFoundError が発生するか検証する."""
        indexer = Indexer(input_dirs=["/non_existent_directory_path_12345"])
        with pytest.raises(FileNotFoundError):
            indexer.load_and_chunk()

    @patch("code_chat_rag.indexer.TextLoader")
    @patch("code_chat_rag.indexer.GenericLoader")
    def test_load_and_chunk_falls_back_to_text_loader_exception(
        self, mock_generic_loader_cls, mock_text_loader_cls, tmp_path
    ):
        """構文解析に失敗した場合, TextLoader によるプレーンテキスト読み込みに切り替わるか検証する."""
        (tmp_path / "main.py").write_text("print('x')", encoding="utf-8")
        mock_generic_loader_cls.from_filesystem.side_effect = RuntimeError("no parser")
        mock_text_loader_cls.return_value.load.return_value = [
            Document(page_content="print('x')", metadata={"source": "main.py"})
        ]

        chunks = Indexer(input_dirs=[str(tmp_path)]).load_and_chunk()

        assert chunks == [
            {"page_content": "print('x')", "metadata": {"source": "main.py"}}
        ]
        mock_text_loader_cls.assert_called_once_with(
            str(tmp_path / "main.py"), encoding="utf-8", autodetect_encoding=True
        )

    @patch("code_chat_rag.indexer.TextLoader")
    @patch("code_chat_rag.indexer.GenericLoader")
    def test_load_and_chunk_skips_unreadable_files_exception(
        self, mock_generic_loader_cls, mock_text_loader_cls, tmp_path, caplog
    ):
        """どちらのローダーでも読み込めないファイルは警告してスキップされるか検証する."""
        (tmp_path / "main.py").write_text("x", encoding="utf-8")
        mock_generic_loader_cls.from_filesystem.side_effect = RuntimeError("no parser")
        mock_text_loader_cls.return_value.load.side_effect = RuntimeError("unreadable")

        chunks = Indexer(input_dirs=[str(tmp_path)]).load_and_chunk()

        assert not chunks
        assert "の読み込みに失敗しました" in caplog.text

    @patch("code_chat_rag.indexer.GenericLoader")
    def test_load_and_chunk_empty_documents(self, mock_loader_cls, tmp_path):
        """該当するドキュメントが存在しなかった場合, 空配列を返すか検証する."""
        repo_dir = tmp_path / "empty_repo"
        repo_dir.mkdir()
        (repo_dir / "main.py").write_text("", encoding="utf-8")

        mock_loader = MagicMock()
        mock_loader.load.return_value = []
        mock_loader_cls.from_filesystem.return_value = mock_loader

        indexer = Indexer(input_dirs=[str(repo_dir)])
        chunks = indexer.load_and_chunk()

        assert not chunks
        mock_loader.load.assert_called_once()

    @patch("code_chat_rag.indexer.GenericLoader")
    def test_load_and_chunk_handles_document_without_metadata(
        self, mock_generic_loader_cls, tmp_path
    ):
        """メタデータが辞書でないドキュメントでも, 汎用スプリッターで分割されるか検証する."""
        (tmp_path / "main.py").write_text("x", encoding="utf-8")
        raw_doc = MagicMock(page_content="hello", metadata=None)
        mock_generic_loader_cls.from_filesystem.return_value.load.return_value = [
            raw_doc
        ]
        splitter = MagicMock()
        splitter.split_documents.return_value = [
            Document(page_content="hello", metadata={})
        ]

        indexer = Indexer(input_dirs=[str(tmp_path)])
        with patch.object(
            indexer, "_get_splitter_for_path", return_value=splitter
        ) as get_splitter:
            chunks = indexer.load_and_chunk()

        get_splitter.assert_called_once_with("")
        assert chunks == [{"page_content": "hello", "metadata": {}}]


class TestGetTargetFiles:
    """`Indexer.get_target_files` のテスト."""

    def test_get_target_files_filters_and_deduplicates_success(self, tmp_path):
        """対象拡張子のみを抽出し, 除外/隠しディレクトリ・重複・存在しないパスを除くか検証する."""
        repo = tmp_path / "repo"
        (repo / "sub").mkdir(parents=True)
        (repo / ".hidden").mkdir()
        (repo / "node_modules").mkdir()
        (repo / "dir.py").mkdir()  # 拡張子が .py でもディレクトリは対象外
        (repo / "a.py").write_text("a", encoding="utf-8")
        (repo / "notes.txt").write_text("n", encoding="utf-8")
        (repo / "sub" / "c.TS").write_text("c", encoding="utf-8")
        (repo / ".hidden" / "d.py").write_text("d", encoding="utf-8")
        (repo / "node_modules" / "e.js").write_text("e", encoding="utf-8")

        indexer = Indexer(input_dirs=[str(repo), str(repo), str(tmp_path / "missing")])

        assert indexer.get_target_files() == [
            str(repo / "a.py"),
            str(repo / "sub" / "c.TS"),
        ]

    def test_get_target_files_warns_missing_path(self, tmp_path, caplog):
        """存在しないパスは, 黙って飛ばさずに, 警告を出すか検証する."""
        missing = tmp_path / "missing"

        assert not Indexer(input_dirs=[str(missing)]).get_target_files()

        assert f"インデックス対象のパスが存在しません: '{missing}'" in caplog.text

    def test_get_target_files_uses_suffixes(self, tmp_path):
        """コンストラクタで指定した拡張子だけを対象にするか検証する."""
        (tmp_path / "a.py").write_text("a", encoding="utf-8")
        (tmp_path / "b.ts").write_text("b", encoding="utf-8")

        indexer = Indexer(input_dirs=[str(tmp_path)], suffixes=[".ts"])

        assert indexer.get_target_files() == [str(tmp_path / "b.ts")]

    def test_get_target_files_ignores_hidden_and_excluded_parents(self, tmp_path):
        """走査対象のパス自体が, 隠しディレクトリや除外ディレクトリ配下にあっても, 対象にするか検証する."""
        repo = tmp_path / ".work" / "build" / "repo"
        repo.mkdir(parents=True)
        (repo / "a.py").write_text("a", encoding="utf-8")

        assert Indexer(input_dirs=[str(repo)]).get_target_files() == [
            str(repo / "a.py")
        ]

    def test_get_target_files_without_input_dirs(self):
        """input_dirs が未指定の場合は空のリストを返すか検証する."""
        assert not Indexer().get_target_files()


class TestGetSplitterForPath:
    """`Indexer._get_splitter_for_path` のテスト."""

    def test_get_splitter_for_path_fallback_success(self) -> None:
        """マッピングにない拡張子（.txt や .unknown など）を指定した場合に汎用スプリッターが返されることを検証."""
        # コンストラクタに必要な依存オブジェクトがあれば MagicMock 等で作成
        indexer = Indexer()

        # pylint: disable=protected-access
        splitter = indexer._get_splitter_for_path("example.txt")

        assert splitter._chunk_size == indexer.chunk_size
        assert splitter._chunk_overlap == indexer.chunk_overlap

    def test_get_splitter_for_path_no_extension(self) -> None:
        """拡張子のないファイルパス（Dockerfile など）を指定した場合のフォールバックを検証."""
        indexer = Indexer()

        # pylint: disable=protected-access
        splitter = indexer._get_splitter_for_path("Dockerfile")

        assert splitter._chunk_size == indexer.chunk_size
        assert splitter._chunk_overlap == indexer.chunk_overlap


class TestGetValidInputDirs:
    """`Indexer._get_valid_input_dirs` のテスト."""

    def test_get_valid_input_dirs_ignores_empty_and_files_success(self, tmp_path):
        """空文字列やファイルパスは有効なディレクトリとして扱われないか検証する."""
        file_path = tmp_path / "file.py"
        file_path.write_text("x", encoding="utf-8")
        valid_dir = tmp_path / "dir"
        valid_dir.mkdir()

        indexer = Indexer(input_dirs=["", str(file_path), str(valid_dir)])

        # pylint: disable-next=protected-access
        assert indexer._get_valid_input_dirs() == [str(valid_dir)]
