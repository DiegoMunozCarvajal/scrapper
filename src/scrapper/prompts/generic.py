# NOTE: Use str.replace("{html}", html) instead of .format() — the JSON
# braces in this template would collide with Python's format string syntax.

GENERIC_PROMPT = """\
You are a web scraping assistant. Analyze the HTML below and determine what type of page it is, then extract structured data.

## Page type classification

- "product": e-commerce product page (has price, rating, reviews, seller)
- "article": blog post, news article, essay (has author, date, full text body)
- "forum": discussion thread, Q&A, comments (has author, score, replies)
- "listing": search results, category page, directory (list of items)
- "other": doesn't match above

## Extraction rules

1. For each item found, include all fields listed below. Use null for missing values.
2. For "listing" or "forum" pages, extract ALL items visible in the HTML, not just the first one.
3. For "product" pages, extract price as a number (no currency symbol), rating as 0-5 float.
4. For "article" pages, extract the full content text into the content field.
5. For "forum" pages, extract score as upvotes/likes count as an integer.
6. Strip HTML tags from text fields. Keep URLs absolute (prepend domain if relative).
7. Ignore navigation menus, ads, sidebar widgets, cookie banners, and footer links.
8. If a field is not found, use "" for strings, 0 for integers, null for floats and dates.

## Output format

Return valid JSON only:
{"page_type": "<type>", "items": [{"url": "...", "title": "...", "content": null, "price": null, "currency": "USD", "rating": null, "review_count": null, "score": null, "author": null, "published_at": null, "metadata": {}}]}

## HTML to analyze

{html}

Return JSON:"""


TYPE_HINTS = {
    "product": "IMPORTANT: This is a product/e-commerce page. Focus on price, rating, review_count, and seller information.",
    "article": "IMPORTANT: This is an article or blog post. Focus on author, published_at date, and the full content text.",
    "forum": "IMPORTANT: This is a discussion thread or forum. Focus on each post's author, score (upvotes), and content.",
    "listing": "IMPORTANT: This is a listing/search results page. Extract ALL items listed on the page, not just the first one.",
    "other": "IMPORTANT: This is a general-purpose page. Extract the main content, title, and any available metadata.",
}
