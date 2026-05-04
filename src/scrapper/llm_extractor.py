import hashlib
import json
import os
import re

from loguru import logger
from openai import APIError, AuthenticationError, OpenAI, RateLimitError

from .llm_cache import LLMCache


_NONCE_PATTERNS = re.compile(
    r'(csrf|nonce|token|timestamp|_t)"?\s*[=:]\s*"?[^"&\s,}]+"?',
    re.IGNORECASE,
)


def _strip_dynamic_html(html: str) -> str:
    return _NONCE_PATTERNS.sub("", html)


class LLMExtractor:
    def __init__(self, model=None, cache_ttl=None, cache_path=None):
        self.model = model or os.getenv("LLM_MODEL", "gpt-4o-mini")
        ttls = cache_ttl if cache_ttl is not None else int(os.getenv("LLM_CACHE_TTL", "86400"))
        path = cache_path or os.getenv("LLM_CACHE_PATH", "llm_cache.db")
        self.cache = LLMCache(db_path=path, ttl=ttls)
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def extract(self, html, prompt_template, item_class, site, query):
        cache_key = self._cache_key(site, query, html)
        if cached := self.cache.get(cache_key):
            logger.info("LLM cache hit for %s:%s", site, query)
            return cached

        chunks = self._chunk_html(html, max_chars=100000)
        all_results = []

        for chunk in chunks:
            prompt = prompt_template.replace("{html}", chunk)
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                    response_format={"type": "json_object"},
                    max_tokens=4096,
                )
                content = response.choices[0].message.content
                data = json.loads(content)
                items = data.get("products", data.get("posts", []))
                if isinstance(items, list):
                    all_results.extend(items)
            except (RateLimitError, AuthenticationError) as e:
                logger.error("OpenAI API error: %s", e)
                return []
            except APIError as e:
                logger.warning("OpenAI API error: %s", e)
                return []
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("LLM returned invalid response: %s", e)
                continue

        if not all_results:
            logger.warning("LLM extraction returned no results for %s:%s", site, query)

        validated = self._validate_items(all_results, item_class)
        if validated:
            self.cache.set(cache_key, validated)
        return validated

    def _chunk_html(self, html, max_chars=100000):
        if len(html) <= max_chars:
            return [html]
        chunks = []
        pos = 0
        while pos < len(html):
            end = pos + max_chars
            if end >= len(html):
                chunks.append(html[pos:])
                break
            last_gt = html.rfind(">", pos, end)
            if last_gt > pos:
                chunks.append(html[pos:last_gt + 1])
                pos = last_gt + 1
            else:
                chunks.append(html[pos:end])
                pos = end
        return chunks

    def _cache_key(self, site, query, html):
        prefix = _strip_dynamic_html(html[:4000] if len(html) > 4000 else html)
        raw = f"{site}:{query}:{prefix}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _validate_items(self, items, item_class):
        if item_class is None or not hasattr(item_class, "fields"):
            return items
        valid_fields = set(item_class.fields.keys())
        validated = []
        for item in items:
            if not isinstance(item, dict):
                continue
            clean = {k: v for k, v in item.items() if k in valid_fields}
            if clean:
                validated.append(clean)
        return validated


def llm_fallback(spider, response, item_class):
    """Shared LLM fallback for any spider. Yields item_class instances."""
    if not os.getenv("OPENAI_API_KEY") or os.getenv("LLM_ENABLED", "true").lower() in ("false", "0", "no"):
        spider.logger.warning("LLM fallback disabled or no API key, skipping")
        return

    prompt_template = getattr(spider, "LLM_PROMPT", None)
    if not prompt_template:
        spider.logger.warning("LLM fallback: spider has no LLM_PROMPT, skipping")
        return

    query = response.meta["query"]
    limit = int(response.meta.get("limit", 10))
    extractor = None

    try:
        extractor = LLMExtractor()
        site = getattr(spider, "site", "unknown")

        items = extractor.extract(
            html=response.text,
            prompt_template=prompt_template,
            item_class=item_class,
            site=site,
            query=query,
        )

        for item_data in items[:limit]:
            item_data.setdefault("metadata", {})
            item_data["metadata"]["strategy"] = "llm"
            item_data["metadata"]["query"] = query
            item_data.setdefault("site", site)
            yield item_class(item_data)
    finally:
        if extractor is not None:
            extractor.cache.close()
