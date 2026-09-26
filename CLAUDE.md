# プロジェクト設定

## コマンド

- ビルド: `uv build`
- 静的解析: `uv run pre-commit run --all-files`
  - `uv run pre-commit` だけでは、ステージ済みファイルが無い場合に全 hook が Skipped になり、何もチェックされない。必ず `run --all-files` を付けること。
  - 内容: trailing-whitespace / ruff format / ruff / pylint / mypy。ファイルを自動修正した場合は失敗扱いになるので、修正後にもう一度実行して全て Passed になることを確認する。
- テスト: `uv run pytest`
  - カバレッジ 100% が合格基準 (`fail_under = 100`)。下回ると pytest が失敗する。
  - 一部のテストだけを実行するときは `--no-cov` を付ける (例: `uv run pytest --no-cov tests/code_chat_cli/test_args.py`)。

## プロジェクト構成

- uv workspace (`packages/*`) による 3 パッケージ構成: `code-chat-cli` (CLI 本体), `code-chat-rag` (RAG), `code-chat-mcp` (MCP)。
- テストは `tests/code_chat_cli/`, `tests/code_chat_rag/`, `tests/code_chat_mcp/` に置く。テストファイル名は、ディレクトリをまたいでも重複させない。
- テストで `CliArgs.parse_args` の戻り値を作るときは、`MagicMock` ではなく `CliArgs` から作る (`tests/conftest.py` の `mock_args`、または `asdict(CliArgs(...))`)。`MagicMock` の属性は常に真値になり、`--dry-run` や `--mcp` の分岐に意図せず入って、実際の API に接続する恐れがある。
- テストから外部 API (Gemini など) や実際の MCP サーバーへ接続しないこと。

## コードの構成規約

- **クラスを持つファイルは 1 ファイル 1 クラス**: クラスを定義するソースファイルには、クラスを 1 つだけ定義する。ファイル名は、クラス名のスネークケースにする (`CacheError` → `cache_error.py`)。`OAuth` のような略語は 1 語として扱う (`OAuthError` → `oauth_error.py`)。
- **クラスにするのは、状態やデータを持つもの**:
  - 状態 (インスタンス変数) を持つもの: `ContextCache` (Gemini クライアントを保持)、`QueryHandler` など。内部関数 (`_` で始まるもの) も、そのクラスのメソッドにする。
  - 例外クラス (`CacheError` など) とデータクラス (`CliArgs`、`McpServerConfig` など): それぞれ専用のファイルに分ける。
  - 定数・プロンプトのようなデータ: クラス属性として持つクラスにする (`constants.py` → `Constants`、`prompts.py` → `Prompts`)。
- **状態を持たない処理は、クラスにしない**: 状態を持たず、メソッドだけになるものは、モジュール直下の関数のままにする (`chat.py`、`history.py`、`file_writer.py` など)。`@staticmethod` だけを並べた、名前空間としてのクラスは作らない。この場合、ファイル名はクラス名と対応しない。
- **クラス本体での自己参照**: メソッドの型注釈や既定値で、そのメソッドが属するクラス自身を参照するときは、文字列にする (`-> "Foo"`)。Python 3.12 / 3.13 では、クラス本体の実行時にクラス名が未定義で `NameError` になるため (Python 3.14 では遅延評価されるので、気づきにくい)。
- **エントリポイント**: `pyproject.toml` の `[project.scripts]` は `code_chat_cli.chat:main` を指す。

## テストの規約

- **ファイル名**: テスト対象の Python ソースのファイル名に `test_` を付ける (`chat.py` → `test_chat.py`)。1 つのソースファイルに対して、テストファイルは 1 つにする。クラスを持つファイル (例外クラス・データクラス・`Constants` / `Prompts` を含む) にも、テストファイルを作る (`cache_error.py` → `test_cache_error.py`)。`__init__.py` は対象外。
- **関数名・メソッド名**: `test_<テスト対象の関数名 (クラスのメソッドはメソッド名)>_<内容>` とする。先頭が `_` の非公開のものは `_` を除いて書く (`_handle_slash_command` → `test_handle_slash_command_...`)。`main()` を経由して内部関数を検証する場合も、検証対象の名前を付ける。クラス自体 (例外・データクラスなど) のテストは、`test_<ファイル名>_<内容>` とする (`test_cache_error_success`)。
- **接尾辞**: テストの内容で決める。1 つのテストでは、複数の接尾辞に該当する内容を検証しない (分ける)。
  - `_success`: 例外を発生させない正常系 (`test_save_chat_history_success`)。例外を伴わないフォールバックも含む (`test_get_git_diff_unstaged_fallback_success`)。
  - `_failure`: 失敗が呼び出し側に伝わる。例外の再送出・`sys.exit(1)` のほか、例外を伴わない異常な入力・状況での中断 (エラー出力を伴う早期リターン) を含む (`test_handle_mcp_subcommand_unknown_action_failure`)。
  - `_exception`: モックなどで例外を発生させ、内部で捕捉して処理が続行・復帰する。リトライ・フォールバック・エラー要素のスキップ・ログ出力のみで終了するものを含む (`test_cleanup_old_backups_unlink_os_error_exception`)。
  - 接尾辞なし: 境界・分岐のテスト。内容を表す名前のままにする (`test_get_target_files_skips_hidden_dirs`)。ただし、名前が `_exception` などの語で終わる場合は、そのまま接尾辞として扱う。
  - シナリオを区別するときは、接尾辞の前に置く。
- **並び順**: テスト対象ソースでの関数・メソッドの定義順に並べる。同じ関数のテストは「_success → _failure → _exception → 境界」の順にする。
- **グルーピング**: テスト対象の関数 (クラスのメソッド) ごとに `class Test<名前のCamelCase>:` でまとめる (`_handle_slash_command` → `TestHandleSlashCommand`)。`# --- 関数名 ---` のような装飾コメントは使わない。クラスはグルーピング専用とし、テストのメソッド名は上記の規約のままにする (`TestHandleSlashCommand.test_handle_slash_command_save_success`)。クラスには `` """`<関数名>` のテスト.""" `` の docstring を付ける (pylint の `missing-class-docstring` 対策)。クラスのメソッドをテストする場合は、`` `クラス名.メソッド名` `` とする (`` `ContextCache.create` ``)。クラス自体のテストは、`class Test<クラス名>:` に `` `<クラス名>` のテスト `` の docstring を付ける。
- 同じ挙動を検証する重複したテストは作らない。

## 開発ルール

- コードの修正後は必ず `uv build` `uv run pre-commit run --all-files` `uv run pytest` を実行し、エラーが出なくなるまで修正を繰り返すこと。
  - **例外**: 変更が Markdown ファイル (`*.md`) のみの場合は、`uv build` `uv run pre-commit run --all-files` `uv run pytest` を実行しない。
- 機能追加・修正には、カバレッジ 100% を保つテストを追加すること。到達不能なデッドコードは削除する。`# pragma: no cover` は、エントリポイント (`__main__`)、型チェッカー向けの防御コード、実行環境依存の分岐に限り、理由をコメントで添えて使う。
- CLI の引数やコマンドを変更したら、`README.md` と `COMMANDS.md` も更新すること。
- pre-commit が README などの行末の空白を自動で削除することがある。意図しない差分が出た場合は、内容に影響がないか確認する。

### 完了条件・タスク完了時の動作

- 修正や機能追加が完了し、ビルドやテストが全て成功したら、以下の手順を実施してタスクを終了すること：
  1. `git diff --stat` を実行して必要に応じて主要ファイルの差分を確認すること。
  2. 修正内容のサマリー（変更点と理由の簡潔なまとめ）をユーザーに報告する。
- ユーザーに依頼されない限り、`git commit` / `git push` は行わない。
