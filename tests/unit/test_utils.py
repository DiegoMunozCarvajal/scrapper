from scrapper.utils import random_user_agent, ensure_dir, slugify, USER_AGENTS
from pathlib import Path
import tempfile


class TestUserAgents:
    def test_user_agents_list_populated(self):
        assert len(USER_AGENTS) > 0

    def test_random_user_agent_returns_valid(self):
        ua = random_user_agent()
        assert ua in USER_AGENTS

    def test_random_user_agent_is_string(self):
        assert isinstance(random_user_agent(), str)


class TestEnsureDir:
    def test_creates_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test_dir"
            ensure_dir(str(path))
            assert path.exists()

    def test_returns_path_object(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test_dir"
            result = ensure_dir(str(path))
            assert isinstance(result, Path)


class TestSlugify:
    def test_basic_slugify(self):
        result = slugify("Hello World")
        assert result == "Hello_World"

    def test_special_chars_removed(self):
        result = slugify("Test@#$%^")
        assert result == "Test"

    def test_leading_trailing_removed(self):
        result = slugify("  Test  ")
        assert result == "Test"