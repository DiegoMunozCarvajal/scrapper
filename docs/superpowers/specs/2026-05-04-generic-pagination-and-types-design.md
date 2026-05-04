# Generic Spider: Pagination + New Page Types

Date: 2026-05-04

## Summary

Add pagination support (traditional links + load more/infinite scroll) and 5 new page types (job, event, recipe, documentation, profile) to the generic spider.

## Architecture

```
src/scrapper/
├── spiders/generic.py      ← pagination loop + Playwright load-more integration
├── prompts/generic.py      ← 5 new type hints + pagination detection in prompt
├── items.py                ← +image_url, +category fields in GenericItem
├── pagination.py           ← NEW: PaginationDetector (CSS → LLM → Playwright)

tests/unit/
├── test_generic_spider.py  ← extended: pagination tests
├── test_generic_prompt.py  ← extended: new type hints
├── test_generic_pagination.py ← NEW: PaginationDetector tests
```

## Flow

```
Request → curl-cffi → extract items (LLM) → detect pagination:
  ├── CSS match → follow with curl-cffi
  ├── LLM detects next_url → follow with curl-cffi
  ├── detects "load more" → switch to Playwright, click loop
  └── no more pages → stop
```

Parameter `limit` controls total items across all pages (not per page). Spider maintains `_items_yielded` counter and stops when limit reached.

## Pagination Module (`pagination.py`)

`PaginationDetector` class with three detection layers:

1. **CSS selectors** (fast, free): `a[rel="next"]`, `link[rel="next"]`, `.pagination .next`, `a[aria-label="Next"]`, `a.next`, `.pager .next`, URL patterns (`?page=N`, `&p=N`)
2. **LLM fallback**: If CSS finds nothing, LLM prompt includes pagination detection instructions; response includes `pagination.next_url`
3. **Playwright detection**: CSS checks for load-more buttons (`button:has-text("Load more")`, `.load-more`, `.infinite-scroll`)

Output type determines spider behavior:

| Detected | Spider action |
|----------|--------------|
| `link` + next_url | `scrapy.Request` via curl-cffi |
| `load_more` | Playwright with JS click loop (max 20 clicks per page, stops when button disappears or no new content) |
| `scroll` | Playwright with JS scroll loop (max 20 scrolls per page, stops when document height stops growing for 3 consecutive scrolls) |
| `None` | End pagination |

The spider tracks `_items_yielded` and stops when reaching `limit`.

## New Fields in GenericItem

```python
image_url = scrapy.Field()  # product image, profile photo, recipe photo
category = scrapy.Field()   # job category, event type, recipe cuisine
```

Type-specific data goes in `metadata` (existing field).

## New Page Types

| Type | Metadata (via LLM) | Key rules |
|------|---------------------|-----------|
| `job` | `{salary, location, company, employment_type}` | Extract salary as number, location as string |
| `event` | `{date, location, organizer, price, venue}` | Date/time as ISO, price as number |
| `recipe` | `{ingredients, cook_time, prep_time, servings, cuisine}` | Ingredients as list of strings, times in minutes |
| `documentation` | `{section, version, framework, language}` | Extract full body content, hierarchical section |
| `profile` | `{bio, location, website, followers, skills}` | Bio text, followers as integer, skills as list |

Type hints prepended to prompt guide the LLM's extraction per type.

## LLM Prompt Changes

- `GENERIC_PROMPT` extended: 5 new types in classification section, pagination detection instructions
- Response format adds optional `pagination` key: `{"next_url": "...", "type": "link"|"load_more"|"scroll"}`
- Backward compatible: pagination key is optional, old behavior preserved

## Spider Changes

```
Spider.parse():
  1. llm_fallback() for items (limit passed via response.meta["limit"])
  2. yield items, track _items_yielded
  3. if _items_yielded >= limit → return
  4. PaginationDetector.find_next_url() or detect_pagination_type()
  5. yield next request (curl-cffi or Playwright) → back to step 1
  6. if load_more/scroll → Playwright with loop → extract from accumulated HTML
```

`start_requests()` must propagate `limit` (default 10) into `response.meta` so `llm_fallback` and the pagination loop can read it.

## Testing

- **PaginationDetector**: unit tests for CSS selectors (HTML fixture with `rel=next`, URL patterns), LLM pagination response parsing, load-more detection
- **GenericSpider**: integration tests for pagination loop (mock LLM responses across pages), load-more Playwright flow, limit enforcement
- **Prompts**: tests for all 10 page types (5 existing + 5 new)
