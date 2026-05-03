import importlib
import os
from unittest.mock import MagicMock, patch


class TestMain:
    def test_main_module_importable(self):
        with patch.dict("sys.modules", {
            "scrapper.scrapers": MagicMock(),
            "scrapper.scrapers.amazon": MagicMock(),
            "scrapper.scrapers.hotmart": MagicMock(),
            "scrapper.scrapers.instagram": MagicMock(),
            "scrapper.scrapers.mercadolibre": MagicMock(),
            "scrapper.scrapers.quora": MagicMock(),
            "scrapper.scrapers.reddit": MagicMock(),
        }):
            import scrapper.main
            assert scrapper.main is not None

    def test_env_loading(self):
        with patch.dict(os.environ, {"SUPABASE_URL": "https://test.supabase.co"}, clear=True):
            importlib.reload(__import__("scrapper.settings", fromlist=["settings"]))
            from scrapper import settings
            assert settings.SUPABASE_URL == "https://test.supabase.co"
