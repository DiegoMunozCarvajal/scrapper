from pathlib import Path


SQL = Path("scripts/setup_supabase.sql").read_text()


def test_posts_schema_contains_reddit_item_columns():
    for column in (
        "link_flair",
        "domain",
        "nsfw",
        "is_self_post",
        "permalink",
    ):
        assert f"ADD COLUMN IF NOT EXISTS {column}" in SQL or f"{column} " in SQL


def test_write_policies_are_scoped_to_service_role():
    assert 'CREATE POLICY "Service can do anything with posts"' in SQL
    assert "ON posts FOR ALL TO service_role" in SQL
    assert "ON products FOR ALL TO service_role" in SQL
    assert "ON scraped_pages FOR ALL TO service_role" in SQL
    assert "ON sites FOR ALL TO service_role" in SQL


def test_public_read_policies_are_select_only():
    assert "ON posts FOR SELECT TO anon, authenticated" in SQL
    assert "ON products FOR SELECT TO anon, authenticated" in SQL
    assert "ON scraped_pages FOR SELECT TO anon, authenticated" in SQL
    assert "ON sites FOR SELECT TO anon, authenticated" in SQL
