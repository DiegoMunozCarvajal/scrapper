"""Unit tests for run_reddit.py — GHA wrapper for Reddit spider."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

import run_reddit


class TestParseQueries:
    def test_parses_valid_json(self, monkeypatch):
        monkeypatch.setenv(
            "REDDIT_QUERIES",
            json.dumps(
                [
                    {"subreddit": "test", "query": "hello", "limit": 10},
                ]
            ),
        )
        result = run_reddit.parse_queries()
        assert result == [{"subreddit": "test", "query": "hello", "limit": 10}]

    def test_missing_env_var_raises(self, monkeypatch):
        monkeypatch.delenv("REDDIT_QUERIES", raising=False)
        with pytest.raises(SystemExit):
            run_reddit.parse_queries()

    def test_invalid_json_raises(self, monkeypatch):
        monkeypatch.setenv("REDDIT_QUERIES", "not json")
        with pytest.raises(SystemExit):
            run_reddit.parse_queries()


class TestBuildScrapyArgs:
    def test_full_query(self):
        q = {"subreddit": "AskReddit", "query": "flirting", "limit": 30}
        result = run_reddit.build_scrapy_args(q)
        assert result == ["-a", "subreddit=AskReddit", "-a", "query=flirting", "-a", "limit=30"]

    def test_query_without_limit(self):
        q = {"subreddit": "test", "query": "hello"}
        result = run_reddit.build_scrapy_args(q)
        assert result == ["-a", "subreddit=test", "-a", "query=hello"]

    def test_query_without_query_key(self):
        q = {"subreddit": "test", "limit": 50}
        result = run_reddit.build_scrapy_args(q)
        assert result == ["-a", "subreddit=test", "-a", "limit=50"]

    def test_query_with_only_subreddit(self):
        q = {"subreddit": "test"}
        result = run_reddit.build_scrapy_args(q)
        assert result == ["-a", "subreddit=test"]


class TestRunWithRetries:
    def test_success_first_attempt(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = run_reddit.run_with_retries(
                ["scrapy", "crawl", "reddit"], max_retries=3, timeout=300
            )
            assert result is True
            assert mock_run.call_count == 1

    def test_retries_on_failure_then_succeeds(self):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=1),
                MagicMock(returncode=1),
                MagicMock(returncode=0),
            ]
            with patch("time.sleep"):
                result = run_reddit.run_with_retries(
                    ["scrapy", "crawl", "reddit"], max_retries=3, timeout=300
                )
                assert result is True
                assert mock_run.call_count == 3

    def test_all_retries_exhausted(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            with patch("time.sleep"):
                result = run_reddit.run_with_retries(
                    ["scrapy", "crawl", "reddit"], max_retries=3, timeout=300
                )
                assert result is False
                assert mock_run.call_count == 3

    def test_timeout_kills_process(self):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd=["scrapy"], timeout=300)
            with patch("time.sleep"):
                result = run_reddit.run_with_retries(
                    ["scrapy", "crawl", "reddit"], max_retries=2, timeout=300
                )
                assert result is False
                assert mock_run.call_count == 2


class TestMain:
    def test_all_queries_pass_exit_zero(self, monkeypatch, tmp_path):
        monkeypatch.setenv(
            "REDDIT_QUERIES",
            json.dumps(
                [
                    {"subreddit": "a", "limit": 10},
                    {"subreddit": "b", "limit": 10},
                ]
            ),
        )
        with patch("run_reddit.run_with_retries", return_value=True):
            with patch("pathlib.Path.mkdir"):
                with pytest.raises(SystemExit) as exc_info:
                    run_reddit.main()
                assert exc_info.value.code == 0

    def test_partial_failure_exit_one(self, monkeypatch, tmp_path):
        monkeypatch.setenv(
            "REDDIT_QUERIES",
            json.dumps(
                [
                    {"subreddit": "a", "limit": 10},
                    {"subreddit": "b", "limit": 10},
                ]
            ),
        )
        with patch("run_reddit.run_with_retries", side_effect=[True, False]):
            with patch("pathlib.Path.mkdir"):
                with pytest.raises(SystemExit) as exc_info:
                    run_reddit.main()
                assert exc_info.value.code == 1

    def test_creates_directories(self, monkeypatch, tmp_path):
        monkeypatch.setenv(
            "REDDIT_QUERIES",
            json.dumps(
                [
                    {"subreddit": "a", "limit": 10},
                ]
            ),
        )
        monkeypatch.chdir(tmp_path)
        with patch("run_reddit.run_with_retries", return_value=True):
            with pytest.raises(SystemExit) as exc_info:
                run_reddit.main()
            assert exc_info.value.code == 0
        assert (tmp_path / "logs").is_dir()
        assert (tmp_path / "metrics").is_dir()
