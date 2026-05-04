from scrapper.prompts.generic import GENERIC_PROMPT, TYPE_HINTS


def test_generic_prompt_contains_html_placeholder():
    assert "{html}" in GENERIC_PROMPT


def test_generic_prompt_mentions_items_key():
    assert '"items"' in GENERIC_PROMPT


def test_generic_prompt_mentions_page_type():
    assert '"page_type"' in GENERIC_PROMPT


def test_generic_prompt_replace_inserts_html():
    result = GENERIC_PROMPT.replace("{html}", "TEST_HTML")
    assert "TEST_HTML" in result


def test_type_hints_all_present():
    for page_type in ("product", "article", "forum", "listing", "other"):
        assert page_type in TYPE_HINTS
        assert len(TYPE_HINTS[page_type]) > 0


def test_type_hint_combined_with_prompt():
    combined = TYPE_HINTS["product"] + "\n\n" + GENERIC_PROMPT
    assert "{html}" in combined
    assert "product" in combined.lower()


def test_new_type_hints_present():
    for page_type in ("job", "event", "recipe", "documentation", "profile"):
        assert page_type in TYPE_HINTS
        assert len(TYPE_HINTS[page_type]) > 0


def test_type_hints_total_count():
    assert len(TYPE_HINTS) == 10


def test_pagination_field_in_prompt():
    assert "pagination" in GENERIC_PROMPT
    assert "next_url" in GENERIC_PROMPT


def test_generic_prompt_mentions_new_types():
    for type_name in ("job", "event", "recipe", "documentation", "profile"):
        assert type_name in GENERIC_PROMPT.lower()


def test_prompt_replace_works_with_new_prompt():
    result = GENERIC_PROMPT.replace("{html}", "TEST_HTML")
    assert "TEST_HTML" in result
    assert '"pagination"' in result
