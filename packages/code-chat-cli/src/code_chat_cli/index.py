"""CLI から呼び出されるインデックス作成および質問応答のハンドラーモジュール."""

from code_chat_rag.code_rag_service import CodeRagService


def handle_index(repo_path: str) -> None:
    """指定されたリポジトリのインデックスを作成し, 結果を標準出力に出力する.

    Args:
        repo_path (str): インデックス作成対象のリポジトリのパス.
    """
    service = CodeRagService(persist_directory="./.chroma_db")
    count = service.index_repository(repo_path)
    print(f"Index completed: {count} chunks added.")


def handle_ask(question: str) -> None:
    """質問に対して CodeRagService を呼び出し, 回答をリアルタイムでストリーミング出力する.

    Args:
        question (str): ユーザーから入力された質問文.
    """
    service = CodeRagService(persist_directory="./.chroma_db")

    # CLI向けにストリーミング出力
    for token in service.ask_stream(question):
        print(token, end="", flush=True)
    print()
