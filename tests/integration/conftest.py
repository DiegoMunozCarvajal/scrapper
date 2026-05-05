"""Shared fixtures for integration tests."""

import json
from pathlib import Path

import pytest


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def reddit_rss():
    path = FIXTURES_DIR / "reddit_rss.xml"
    return path.read_text()


@pytest.fixture
def reddit_json_search():
    path = FIXTURES_DIR / "reddit_search.json"
    return json.loads(path.read_text())


@pytest.fixture
def reddit_json_comments():
    path = FIXTURES_DIR / "reddit_comments.json"
    return json.loads(path.read_text())


@pytest.fixture
def hotmart_api_json():
    path = FIXTURES_DIR / "hotmart_api_response.json"
    return path.read_text()


@pytest.fixture
def hotmart_search_html():
    path = FIXTURES_DIR / "hotmart_search.html"
    return path.read_text()
