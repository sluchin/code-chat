"""`code_chat_rag.code_indexer` モジュールのテスト."""

from unittest.mock import ANY, MagicMock, patch

import pytest
from code_chat_rag.code_indexer import CodeIndexer
from langchain_core.documents import Document


def test_code_indexer_init():
    """初期化パラメータが正しく保持されるか検証する."""
    indexer = CodeIndexer(
        repo_path="/dummy/repo",
        suffixes=[".py", ".ts"],
        chunk_size=500,
        chunk_overlap=50,
    )

    assert indexer.repo_path == "/dummy/repo"
    assert indexer.suffixes == [".py", ".ts"]
    assert indexer.chunk_size == 500
    assert indexer.chunk_overlap == 50


def test_load_and_chunk_file_not_found():
    """存在しないパスを指定した場合に FileNotFoundError が発生するか検証する."""
    indexer = CodeIndexer(repo_path="/non_existent_directory_path_12345")
    with pytest.raises(FileNotFoundError):
        indexer.load_and_chunk()


@patch("code_chat_rag.code_indexer.GenericLoader")
@patch("code_chat_rag.code_indexer.RecursiveCharacterTextSplitter")
def test_load_and_chunk_success(mock_splitter_cls, mock_loader_cls, tmp_path):
    """ファイルロードからチャンク分割, 辞書型配列への変換までの一連の流れを検証する."""
    # 実在する一時ディレクトリを準備
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

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
        Document(page_content="def main():", metadata={"source": "main.py", "line": 1}),
        Document(page_content="    pass", metadata={"source": "main.py", "line": 2}),
    ]
    mock_splitter.split_documents.return_value = split_docs
    mock_splitter_cls.from_language.return_value = mock_splitter

    # テスト対象の実行
    indexer = CodeIndexer(repo_path=str(repo_dir))
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
    mock_loader_cls.from_filesystem.assert_called_once_with(
        path=str(repo_dir),
        glob="**/*",
        suffixes=[".py", ".cpp", ".hpp", ".c", ".h", ".ts", ".js"],
        parser=ANY,
    )
    mock_loader.load.assert_called_once()
    mock_splitter.split_documents.assert_called_once_with(raw_docs)


@patch("code_chat_rag.code_indexer.GenericLoader")
def test_load_and_chunk_empty_documents(mock_loader_cls, tmp_path):
    """該当するドキュメントが存在しなかった場合, 空配列を返すか検証する."""
    repo_dir = tmp_path / "empty_repo"
    repo_dir.mkdir()

    mock_loader = MagicMock()
    mock_loader.load.return_value = []
    mock_loader_cls.from_filesystem.return_value = mock_loader

    indexer = CodeIndexer(repo_path=str(repo_dir))
    chunks = indexer.load_and_chunk()

    assert not chunks
    mock_loader.load.assert_called_once()


def test_get_splitter_for_path_fallback() -> None:
    """マッピングにない拡張子（.txt や .unknown など）を指定した場合に汎用スプリッターが返されることを検証."""
    # コンストラクタに必要な依存オブジェクトがあれば MagicMock 等で作成
    indexer = CodeIndexer()

    # pylint: disable=protected-access
    splitter = indexer._get_splitter_for_path("example.txt")

    assert splitter._chunk_size == indexer.chunk_size
    assert splitter._chunk_overlap == indexer.chunk_overlap


def test_get_splitter_for_path_no_extension() -> None:
    """拡張子のないファイルパス（Dockerfile など）を指定した場合のフォールバックを検証."""
    indexer = CodeIndexer()

    # pylint: disable=protected-access
    splitter = indexer._get_splitter_for_path("Dockerfile")

    assert splitter._chunk_size == indexer.chunk_size
    assert splitter._chunk_overlap == indexer.chunk_overlap
