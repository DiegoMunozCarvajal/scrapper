HOTMART_PROMPT = """\
You are a web scraper assistant. Extract product information from this HTML page
of Hotmart marketplace search results.

For each product found, extract these fields:
- title: the product name (string)
- url: the product page URL / href (string)
- price: the numeric price value, e.g. 49.99 (float or null)
- rating: the numeric rating, e.g. 4.5 (float or null, 1-5 scale)
- review_count: number of reviews as integer, e.g. 234 (int or 0)
- seller: the author/seller name (string or "")

Rules:
- Ignore banners, ads, navigation, and footer content
- If a field is not found, use "" for strings, 0 for integers, null for floats
- Only extract products that appear as cards in the search results

Return a JSON object with a "products" key containing an array of objects:
{"products": [{"title": "Example Course", "url": "...", "price": 49.99, "rating": 4.5, "review_count": 234, "seller": "Author Name"}]}

HTML:
{html}"""
