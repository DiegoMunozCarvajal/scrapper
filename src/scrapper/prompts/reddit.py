REDDIT_PROMPT = """\
You are a web scraper assistant. Extract Reddit posts from this search results
page on old.reddit.com.

For each post found, extract these fields:
- title: the post title (string)
- url: the post URL, relative or absolute (string)
- author: username of the poster, e.g. "u/someuser" (string)
- score: upvote count as integer, e.g. 142 (int or 0)
- comment_count: number of comments as integer, e.g. 23 (int or 0)
- published_at: date in ISO 8601 format if available (string or null)

Rules:
- Ignore promoted posts, ads, and sticky/pinned content
- If a field is not found, use "" for strings, 0 for integers, null for dates
- Only extract posts from the search results listing, not the sidebar

Return a JSON object with a "posts" key containing an array of objects:
{"posts": [{"title": "Post Title", "url": "/r/python/comments/...", "author": "u/username", "score": 142, "comment_count": 23, "published_at": "2024-01-01T00:00:00Z"}]}

HTML:
{html}"""
