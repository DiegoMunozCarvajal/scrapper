from scrapper.prompts.hotmart import HOTMART_PROMPT
from scrapper.prompts.reddit import REDDIT_PROMPT


def test_hotmart_prompt_contains_html_placeholder():
    assert "{html}" in HOTMART_PROMPT


def test_hotmart_prompt_mentions_products_key():
    assert '"products"' in HOTMART_PROMPT


def test_reddit_prompt_contains_html_placeholder():
    assert "{html}" in REDDIT_PROMPT


def test_reddit_prompt_mentions_posts_key():
    assert '"posts"' in REDDIT_PROMPT


def test_hotmart_prompt_replace_inserts_html():
    result = HOTMART_PROMPT.replace("{html}", "TEST_HTML")
    assert "TEST_HTML" in result


def test_reddit_prompt_replace_inserts_html():
    result = REDDIT_PROMPT.replace("{html}", "TEST_HTML")
    assert "TEST_HTML" in result
