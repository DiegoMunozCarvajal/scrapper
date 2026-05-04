# NOTE: Use str.replace("{html}", html) instead of .format() — the JSON
# braces in this template would collide with Python's format string syntax.

GENERIC_PROMPT = """\
You are a web scraping assistant. Analyze the HTML below and determine what type of page it is, then extract structured data.

## Page type classification

- "product": e-commerce product page (has price, rating, reviews, seller)
- "article": blog post, news article, essay (has author, date, full text body)
- "forum": discussion thread, Q&A, comments (has author, score, replies)
- "listing": search results, category page, directory (list of items)
- "job": job listing or job search results (has company, salary, location)
- "event": event page, conference, meetup (has date, venue, organizer)
- "recipe": cooking recipe (has ingredients, cook time, instructions)
- "documentation": docs, wiki, API reference (has sections, code examples)
- "profile": person or organization profile (has bio, photo, links)
- "other": doesn't match above

## Pagination detection

Examine the HTML for pagination controls and report them:
- Look for "next page" links, page number links, load more buttons, or infinite scroll indicators
- If a next page URL is found, include it in pagination.next_url
- If load more / show more buttons exist, set pagination.type to "load_more"
- If infinite scroll is detected, set pagination.type to "scroll"
- If no pagination is found, omit the pagination key entirely

## Extraction rules

1. For each item found, include all fields listed below. Use null for missing values.
2. For "listing", "forum", "job", "event", or "recipe" pages, extract ALL items visible in the HTML, not just the first one.
3. For "product" or "event" pages, extract price as a number (no currency symbol), rating as 0-5 float.
4. For "article", "documentation", or "profile" pages, extract the full content text into the content field.
5. For "forum" pages, extract score as upvotes/likes count as an integer.
6. For "recipe" pages, put ingredients as a list of strings in metadata.ingredients.
7. Strip HTML tags from text fields. Keep URLs absolute (prepend domain if relative).
8. Ignore navigation menus, ads, sidebar widgets, cookie banners, and footer links.
9. If a field is not found, use "" for strings, 0 for integers, null for floats and dates.

## Output format

Return valid JSON only:
{"page_type": "<type>", "pagination": {"next_url": "<absolute_url_or_null>", "type": "link"|"load_more"|"scroll"}, "items": [{"url": "...", "title": "...", "content": null, "price": null, "currency": "USD", "rating": null, "review_count": null, "score": null, "author": null, "published_at": null, "image_url": null, "category": null, "metadata": {}}]}

The pagination key is optional — omit it if no pagination exists on the page.

## HTML to analyze

{html}

Return JSON:"""


TYPE_HINTS = {
    "product": "IMPORTANT: This is a product/e-commerce page. Focus on price, rating, review_count, and seller information.",
    "article": "IMPORTANT: This is an article or blog post. Focus on author, published_at date, and the full content text.",
    "forum": "IMPORTANT: This is a discussion thread or forum. Focus on each post's author, score (upvotes), and content.",
    "listing": "IMPORTANT: This is a listing/search results page. Extract ALL items listed on the page, not just the first one.",
    "other": "IMPORTANT: This is a general-purpose page. Extract the main content, title, and any available metadata.",
    "job": "IMPORTANT: This is a job listing. Extract job title, company name as author, salary as price (number, no currency symbol), location, employment_type in metadata. Use category for job category (Engineering, Marketing, etc.).",
    "event": "IMPORTANT: This is an event page. Extract event name as title, date in metadata, location, organizer as author, price as number, venue in metadata. Use category for event type (Conference, Workshop, etc.).",
    "recipe": "IMPORTANT: This is a recipe page. Extract recipe name as title, ingredients as a list in metadata.ingredients, cook_time and prep_time as numbers (minutes) in metadata, servings, cuisine in category. Put full instructions in content.",
    "documentation": "IMPORTANT: This is a documentation or wiki page. Extract page title, full content body, section hierarchy in metadata.section, version/framework info in metadata. Use category for the product/framework name.",
    "profile": "IMPORTANT: This is a profile page. Extract person/org name as title, bio as content, location, website, followers (as integer) in metadata, skills as list in metadata. Use image_url for profile photo. Use category for profile type.",
}
