import os
import pytest
from supabase import create_client


@pytest.mark.skipif(
    not os.getenv("SUPABASE_URL") or not os.getenv("SUPABASE_KEY"),
    reason="Supabase credentials not configured"
)
class TestSupabaseIntegration:
    def test_connection_succeeds(self):
        client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_KEY"],
        )
        result = client.table("posts").select("*", count="exact").execute()
        assert hasattr(result, "count") or hasattr(result, "data")

    def test_posts_table_exists(self):
        client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_KEY"],
        )
        result = client.table("posts").select("*").limit(1).execute()
        assert result.data is not None

    def test_products_table_exists(self):
        client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_KEY"],
        )
        result = client.table("products").select("*").limit(1).execute()
        assert result.data is not None

    def test_upsert_and_read_post(self):
        client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_KEY"],
        )
        test_url = "https://test.example.com/verify_upsert"
        client.table("posts").upsert(
            {"site": "test", "url": test_url, "title": "verify_upsert"},
            on_conflict="site,url",
        ).execute()
        result = client.table("posts").select("*").eq("url", test_url).execute()
        assert len(result.data) >= 1
        client.table("posts").delete().eq("url", test_url).execute()
