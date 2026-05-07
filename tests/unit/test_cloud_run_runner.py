"""Unit tests for cloud_run_runner.py"""

import json
import os
import signal
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Import the module under test
import cloud_run_runner as runner


@pytest.fixture(autouse=True)
def reset_global_state():
    """Reset global state before each test."""
    runner._lock_acquired = False
    runner._terminate = False
    runner._child = None
    yield
    runner._lock_acquired = False
    runner._terminate = False
    runner._child = None


class TestCloudRunRunnerLocking:
    """Tests for distributed lock acquire/release."""

    @patch.dict(os.environ, {"SUPABASE_URL": "http://localhost", "SUPABASE_KEY": "test"})
    @patch("supabase.create_client")
    def test_acquire_lock_success_via_rpc(self, mock_create_client):
        """Lock acquisition succeeds when RPC returns True."""
        mock_client = MagicMock()
        mock_client.rpc.return_value.execute.return_value.data = True
        mock_create_client.return_value = mock_client

        result = runner.acquire_lock("reddit")
        assert result is True
        assert runner._lock_acquired is True
        mock_client.rpc.assert_called_once()
        call_args = mock_client.rpc.call_args
        # rpc is called with positional args: rpc(name, params_dict)
        assert call_args[0][0] == "acquire_spider_lock"
        assert call_args[0][1]["p_spider"] == "reddit"

    @patch.dict(os.environ, {"SUPABASE_URL": "http://localhost", "SUPABASE_KEY": "test"})
    @patch("supabase.create_client")
    def test_acquire_lock_already_taken(self, mock_create_client):
        """Lock acquisition returns False when already taken."""
        mock_client = MagicMock()
        mock_client.rpc.return_value.execute.return_value.data = False
        mock_create_client.return_value = mock_client

        result = runner.acquire_lock("reddit")
        assert result is False
        assert runner._lock_acquired is False

    @patch.dict(os.environ, {"SUPABASE_URL": "http://localhost", "SUPABASE_KEY": "test"})
    @patch("supabase.create_client")
    def test_acquire_lock_fallback_to_insert(self, mock_create_client):
        """Falls back to direct insert when RPC function does not exist."""
        mock_client = MagicMock()
        mock_client.rpc.side_effect = Exception(
            'function "acquire_spider_lock" does not exist'
        )
        mock_client.table.return_value.delete.return_value.lt.return_value.execute.return_value = None
        mock_client.table.return_value.insert.return_value.execute.return_value = None
        mock_create_client.return_value = mock_client

        result = runner.acquire_lock("reddit")
        assert result is True
        assert runner._lock_acquired is True
        mock_client.table.assert_called_with("spider_locks")

    @patch.dict(os.environ, {"SUPABASE_URL": "http://localhost", "SUPABASE_KEY": "test"})
    @patch("supabase.create_client")
    def test_acquire_lock_unique_violation(self, mock_create_client):
        """Unique violation on insert means lock is already held."""
        mock_client = MagicMock()
        mock_client.rpc.side_effect = Exception(
            'function "acquire_spider_lock" does not exist'
        )
        mock_client.table.return_value.delete.return_value.lt.return_value.execute.return_value = None
        mock_client.table.return_value.insert.return_value.execute.side_effect = Exception(
            "duplicate key value violates unique constraint"
        )
        mock_create_client.return_value = mock_client

        result = runner.acquire_lock("reddit")
        assert result is False
        assert runner._lock_acquired is False

    @patch.dict(os.environ, {"SUPABASE_URL": "http://localhost", "SUPABASE_KEY": "test"})
    @patch("supabase.create_client")
    def test_release_lock_deletes_row(self, mock_create_client):
        """Release lock deletes the spider row."""
        mock_client = MagicMock()
        mock_create_client.return_value = mock_client
        runner._lock_acquired = True

        runner.release_lock("reddit")

        assert runner._lock_acquired is False
        mock_client.table.assert_called_with("spider_locks")

    @patch.dict(os.environ, {}, clear=True)
    def test_acquire_lock_no_credentials_returns_true(self):
        """Without Supabase credentials, lock is skipped (returns True)."""
        result = runner.acquire_lock("reddit")
        assert result is True

    @patch.dict(os.environ, {}, clear=True)
    def test_release_lock_no_credentials_does_nothing(self):
        """Without Supabase credentials, release is a no-op."""
        runner._lock_acquired = True
        runner.release_lock("reddit")
        assert runner._lock_acquired is True  # remains True (no-op)


class TestCloudRunRunnerSpiderExecution:
    """Tests for run_spider and task dispatch."""

    def test_run_spider_dry_run_returns_true(self, capsys):
        """Dry run should log and return True without executing."""
        result = runner.run_spider("reddit", {"query": "python"}, dry_run=True)
        assert result is True
        captured = capsys.readouterr()
        assert "[DRY-RUN]" in captured.out

    @patch("cloud_run_runner.subprocess.Popen")
    def test_run_spider_success(self, mock_popen):
        """Successful scrapy execution returns True."""
        mock_proc = MagicMock()
        mock_proc.poll.side_effect = [None, 0]  # running, then done
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        result = runner.run_spider("reddit", {"query": "python"})
        assert result is True
        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == sys.executable
        assert "scrapy" in cmd
        assert "reddit" in cmd

    @patch("cloud_run_runner.subprocess.Popen")
    def test_run_spider_failure_retries(self, mock_popen):
        """Failed scrapy execution retries up to MAX_RETRIES."""
        mock_proc = MagicMock()
        mock_proc.poll.side_effect = [None, 1]  # running, then exit 1
        mock_proc.returncode = 1
        mock_popen.return_value = mock_proc

        orig_retries = runner.MAX_RETRIES_PER_QUERY
        runner.MAX_RETRIES_PER_QUERY = 2
        try:
            result = runner.run_spider("reddit", {"query": "python"})
            assert result is False
            assert mock_popen.call_count == 2
        finally:
            runner.MAX_RETRIES_PER_QUERY = orig_retries

    @patch("cloud_run_runner.subprocess.Popen")
    def test_run_spider_sigterm_no_retry(self, mock_popen):
        """SIGTERM should not trigger retries."""
        mock_proc = MagicMock()
        mock_proc.poll.side_effect = [None, -signal.SIGTERM]
        mock_proc.returncode = -signal.SIGTERM
        mock_popen.return_value = mock_proc

        result = runner.run_spider("reddit", {"query": "python"})
        assert result is False
        assert mock_popen.call_count == 1


class TestCloudRunRunnerArgs:
    """Tests for CLI argument parsing and validation."""

    def test_main_no_spider_exits(self, capsys):
        """Running without spider argument should exit."""
        with patch.object(sys, "argv", ["cloud_run_runner.py"]):
            with pytest.raises(SystemExit) as exc_info:
                runner.main()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Debes especificar un spider" in captured.out

    @patch.dict(os.environ, {}, clear=True)
    def test_main_missing_env_vars_exits(self, capsys):
        """Missing required env vars should exit."""
        with patch.object(sys, "argv", ["cloud_run_runner.py", "reddit"]):
            with pytest.raises(SystemExit) as exc_info:
                runner.main()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Faltan variables de entorno" in captured.out

    @patch.dict(os.environ, {"SUPABASE_URL": "x", "SUPABASE_KEY": "x", "OPENAI_API_KEY": "x"})
    @patch("cloud_run_runner.QUERIES_FILE")
    def test_main_missing_queries_json_exits(self, mock_queries_file, capsys):
        """Missing queries.json should exit."""
        mock_queries_file.exists.return_value = False
        with patch.object(sys, "argv", ["cloud_run_runner.py", "reddit"]):
            with pytest.raises(SystemExit) as exc_info:
                runner.main()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "no se encontró" in captured.out.lower()

    @patch.dict(os.environ, {"SUPABASE_URL": "x", "SUPABASE_KEY": "x", "OPENAI_API_KEY": "x"})
    @patch("cloud_run_runner.QUERIES_FILE")
    def test_main_invalid_json_exits(self, mock_queries_file, capsys):
        """Invalid JSON in queries.json should exit."""
        mock_queries_file.exists.return_value = True
        mock_queries_file.read_text.return_value = "not json"
        with patch.object(sys, "argv", ["cloud_run_runner.py", "reddit"]):
            with pytest.raises(SystemExit) as exc_info:
                runner.main()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "JSON inválido" in captured.out

    @patch.dict(os.environ, {"SUPABASE_URL": "x", "SUPABASE_KEY": "x", "OPENAI_API_KEY": "x"})
    @patch("cloud_run_runner.QUERIES_FILE")
    def test_main_spider_not_in_queries_exits(self, mock_queries_file, capsys):
        """Spider not found in queries.json should exit."""
        mock_queries_file.exists.return_value = True
        mock_queries_file.read_text.return_value = json.dumps({"hotmart": {"queries": []}})
        with patch.object(sys, "argv", ["cloud_run_runner.py", "reddit"]):
            with pytest.raises(SystemExit) as exc_info:
                runner.main()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "no existe en queries.json" in captured.out


class TestCloudRunRunnerSignalHandling:
    """Tests for SIGTERM/SIGINT handling."""

    def test_handle_signal_sets_terminate(self):
        """Signal handler should set _terminate flag."""
        runner._terminate = False
        runner._handle_signal(signal.SIGTERM, None)
        assert runner._terminate is True

        runner._terminate = False
        runner._handle_signal(signal.SIGINT, None)
        assert runner._terminate is True


class TestCloudRunRunnerTaskDispatch:
    """Tests for task argument building."""

    @patch.dict(os.environ, {"SUPABASE_URL": "x", "SUPABASE_KEY": "x", "OPENAI_API_KEY": "x"})
    @patch("cloud_run_runner.QUERIES_FILE")
    @patch("cloud_run_runner.run_spider")
    @patch("cloud_run_runner.acquire_lock")
    @patch("cloud_run_runner.release_lock")
    def test_main_dry_run_dispatches_subreddit_tasks(
        self, mock_release, mock_acquire, mock_run_spider, mock_queries_file, capsys
    ):
        """Dry run should dispatch subreddit tasks correctly."""
        mock_queries_file.exists.return_value = True
        mock_queries_file.read_text.return_value = json.dumps(
            {
                "reddit": {
                    "queries": [
                        {"subreddit": "python", "limit": 10},
                        {"subreddit": "django", "limit": 5, "query": "orm"},
                    ]
                }
            }
        )
        mock_acquire.return_value = True
        mock_run_spider.return_value = True

        with patch.object(sys, "argv", ["cloud_run_runner.py", "reddit", "--dry-run"]):
            runner.main()

        assert mock_run_spider.call_count == 2
        assert mock_run_spider.call_args_list[0][0][0] == "reddit"
        assert mock_run_spider.call_args_list[0][1]["dry_run"] is True
        args2 = mock_run_spider.call_args_list[1][0][1]
        assert args2["subreddit"] == "django"
        assert args2["query"] == "orm"

    @patch.dict(os.environ, {"SUPABASE_URL": "x", "SUPABASE_KEY": "x", "OPENAI_API_KEY": "x"})
    @patch("cloud_run_runner.QUERIES_FILE")
    @patch("cloud_run_runner.run_spider")
    @patch("cloud_run_runner.acquire_lock")
    @patch("cloud_run_runner.release_lock")
    def test_main_dry_run_dispatches_url_tasks(
        self, mock_release, mock_acquire, mock_run_spider, mock_queries_file, capsys
    ):
        """Dry run should dispatch URL tasks correctly."""
        mock_queries_file.exists.return_value = True
        mock_queries_file.read_text.return_value = json.dumps(
            {
                "generic": {
                    "queries": [
                        {"url": "https://example.com", "type": "article"},
                    ]
                }
            }
        )
        mock_acquire.return_value = True
        mock_run_spider.return_value = True

        with patch.object(sys, "argv", ["cloud_run_runner.py", "generic", "--dry-run"]):
            runner.main()

        assert mock_run_spider.call_count == 1
        args = mock_run_spider.call_args_list[0][0][1]
        assert args["url"] == "https://example.com"
        assert args["type"] == "article"

    @patch.dict(os.environ, {"SUPABASE_URL": "x", "SUPABASE_KEY": "x", "OPENAI_API_KEY": "x"})
    @patch("cloud_run_runner.QUERIES_FILE")
    @patch("cloud_run_runner.run_spider")
    @patch("cloud_run_runner.acquire_lock")
    @patch("cloud_run_runner.release_lock")
    def test_main_partial_failure_exit_code_2(
        self, mock_release, mock_acquire, mock_run_spider, mock_queries_file
    ):
        """>50% failure rate should exit with code 2."""
        mock_queries_file.exists.return_value = True
        mock_queries_file.read_text.return_value = json.dumps(
            {
                "reddit": {
                    "queries": [
                        {"subreddit": "a", "limit": 10},
                        {"subreddit": "b", "limit": 10},
                        {"subreddit": "c", "limit": 10},
                    ]
                }
            }
        )
        mock_acquire.return_value = True
        mock_run_spider.side_effect = [True, False, False]  # 2/3 fail = 66%

        with patch.object(sys, "argv", ["cloud_run_runner.py", "reddit"]):
            with pytest.raises(SystemExit) as exc_info:
                runner.main()
        assert exc_info.value.code == 2

    @patch.dict(os.environ, {"SUPABASE_URL": "x", "SUPABASE_KEY": "x", "OPENAI_API_KEY": "x"})
    @patch("cloud_run_runner.QUERIES_FILE")
    @patch("cloud_run_runner.run_spider")
    @patch("cloud_run_runner.acquire_lock")
    @patch("cloud_run_runner.release_lock")
    def test_main_all_fail_exit_code_1(
        self, mock_release, mock_acquire, mock_run_spider, mock_queries_file
    ):
        """100% failure rate should exit with code 1."""
        mock_queries_file.exists.return_value = True
        mock_queries_file.read_text.return_value = json.dumps(
            {
                "reddit": {
                    "queries": [
                        {"subreddit": "a", "limit": 10},
                    ]
                }
            }
        )
        mock_acquire.return_value = True
        mock_run_spider.return_value = False

        with patch.object(sys, "argv", ["cloud_run_runner.py", "reddit"]):
            with pytest.raises(SystemExit) as exc_info:
                runner.main()
        assert exc_info.value.code == 1

    @patch.dict(os.environ, {"SUPABASE_URL": "x", "SUPABASE_KEY": "x", "OPENAI_API_KEY": "x"})
    @patch("cloud_run_runner.QUERIES_FILE")
    @patch("cloud_run_runner.run_spider")
    @patch("cloud_run_runner.acquire_lock")
    @patch("cloud_run_runner.release_lock")
    def test_main_job_name_mapping(
        self, mock_release, mock_acquire, mock_run_spider, mock_queries_file
    ):
        """Job name can map to different spider name via 'spider' key."""
        mock_queries_file.exists.return_value = True
        mock_queries_file.read_text.return_value = json.dumps(
            {
                "reddit-evening": {
                    "spider": "reddit",
                    "queries": [{"subreddit": "AskWomen", "limit": 50}],
                }
            }
        )
        mock_acquire.return_value = True
        mock_run_spider.return_value = True

        with patch.object(sys, "argv", ["cloud_run_runner.py", "reddit-evening", "--dry-run"]):
            runner.main()

        assert mock_run_spider.call_args[0][0] == "reddit"
