import hashlib
import json
from pathlib import Path

from loguru import logger

from .items import PostItem
from .utils import slugify


class MarkdownExportPipeline:
    """Convert each scraped item to a Markdown file with YAML frontmatter."""

    def __init__(self, output_dir: str = "rag_output"):
        self.output_dir = Path(output_dir)
        self._collision_counters: dict[str, int] = {}

    def open_spider(self, spider):
        posts_dir = self.output_dir / "posts"
        products_dir = self.output_dir / "products"
        posts_dir.mkdir(parents=True, exist_ok=True)
        products_dir.mkdir(parents=True, exist_ok=True)
        self._collision_counters = {}
        logger.info(f"Markdown export dirs ready: {self.output_dir}")

    def close_spider(self, spider):
        self._collision_counters = {}

    def process_item(self, item, spider):
        is_post = isinstance(item, PostItem)
        site = item.get("site", "unknown")
        source_type = "social_media" if is_post else "product_listing"

        title = item.get("title", "untitled")
        raw_slug = slugify(title).lower()[:80].strip("_")
        slug = raw_slug or "untitled"

        target_dir = self.output_dir / ("posts" if is_post else "products")
        target_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{site}-{slug}.md"
        filepath = target_dir / filename

        if filepath.exists():
            counter_key = str(filepath)
            count = self._collision_counters.get(counter_key, 1) + 1
            self._collision_counters[counter_key] = count
            filename = f"{site}-{slug}-{count}.md"
            filepath = target_dir / filename

        frontmatter = self._build_frontmatter(item, source_type)
        content = item.get("content") or ""
        body = f"# {title}\n\n{content}" if content else f"# {title}"
        md = f"---\n{frontmatter}---\n\n{body}\n"

        try:
            filepath.write_text(md)
        except OSError as e:
            logger.error(f"Failed to write markdown file {filepath}: {e}")
        return item

    def _build_frontmatter(self, item, source_type: str) -> str:
        data = dict(item)
        data["source_type"] = source_type

        lines = []
        for key in ("site", "url", "title", "author", "score", "comments",
                     "price", "currency", "rating", "review_count", "seller",
                     "scraped_at", "source_type"):
            val = data.get(key)
            if val is None:
                continue
            if isinstance(val, str) and _needs_quoting(val):
                lines.append(f'{key}: "{val}"')
            else:
                lines.append(f"{key}: {val}")
        return "\n".join(lines) + "\n"


class ChunkedJSONPipeline:
    """Export items as JSONL chunks optimized for vector DB ingestion."""

    def __init__(self, output_dir: str = "rag_output"):
        self.output_dir = Path(output_dir)
        self._file = None

    def open_spider(self, spider):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"JSONL export ready: {self.output_dir}")

    def close_spider(self, spider):
        if self._file:
            self._file.close()
            self._file = None

    def process_item(self, item, spider):
        chunk = self._build_chunk(item)
        try:
            if self._file is None:
                self._file = open(self.output_dir / "chunks.jsonl", "a")
            self._file.write(json.dumps(chunk, ensure_ascii=False) + "\n")
            self._file.flush()
        except OSError as e:
            logger.error(f"Failed to write JSONL chunk: {e}")
        return item

    def _build_chunk(self, item) -> dict:
        is_post = isinstance(item, PostItem)
        source_type = "social_media" if is_post else "product_listing"
        url = item.get("url", "")
        chunk_hash = hashlib.sha256(url.encode()).hexdigest()[:8]
        if not url:
            chunk_hash = hashlib.sha256(item.get("title", "").encode()).hexdigest()[:8]

        site = item.get("site", "unknown")
        title = item.get("title", "untitled")
        content = item.get("content") or ""

        text = f"# {title}" + (f"\n\n{content}" if content else "")

        metadata = dict(item)
        metadata["source_type"] = source_type
        metadata.pop("content", None)

        return {
            "chunk_id": f"{site}-{chunk_hash}",
            "text": text,
            "metadata": metadata,
        }


def _needs_quoting(val: str) -> bool:
    return any(c in val for c in ':{}[]&*?|><#%"\'@`!\n') or val.startswith(" ") or val.endswith(" ")
