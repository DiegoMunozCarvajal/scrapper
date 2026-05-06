import json
import tempfile
from pathlib import Path
from scrapper.items import GenericItem, PostItem, ProductItem
from scrapper.rag_export import MarkdownExportPipeline, ChunkedJSONPipeline


class FakeSpider:
    name = "test_spider"


class TestMarkdownExportPipeline:
    def test_open_spider_creates_output_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pipe = MarkdownExportPipeline(output_dir=tmpdir)
            pipe.open_spider(spider=None)
            assert Path(tmpdir, "posts").exists()
            assert Path(tmpdir, "products").exists()

    def test_process_item_writes_markdown_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pipe = MarkdownExportPipeline(output_dir=tmpdir)
            pipe.open_spider(spider=None)
            item = PostItem(
                site="reddit",
                url="https://old.reddit.com/r/Python/comments/abc123",
                title="How I Learned Python!",
                author="r/PythonLearning",
                content="This is the post content.",
                score=42,
                comment_count=10,
            )
            result = pipe.process_item(item, spider=None)
            assert result is item

            files = list(Path(tmpdir, "posts").glob("*.md"))
            assert len(files) == 1
            content = files[0].read_text()
            assert "---" in content
            assert "site: reddit" in content
            assert 'title: "How I Learned Python!"' in content
            assert "source_type: social_media" in content
            assert "# How I Learned Python!" in content
            assert "This is the post content." in content

    def test_markdown_content_none_uses_title_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pipe = MarkdownExportPipeline(output_dir=tmpdir)
            pipe.open_spider(spider=None)
            item = PostItem(
                site="reddit",
                url="https://example.com/post",
                title="No Content Post",
                content=None,
            )
            pipe.process_item(item, spider=None)
            files = list(Path(tmpdir, "posts").glob("*.md"))
            content = files[0].read_text()
            assert "# No Content Post" in content
            body = content.split("---\n")[-1]
            assert body.strip() == "# No Content Post"

    def test_markdown_slug_from_title(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pipe = MarkdownExportPipeline(output_dir=tmpdir)
            pipe.open_spider(spider=None)
            item = PostItem(
                site="reddit",
                url="https://example.com/1",
                title="How I Learned Python!",
            )
            pipe.process_item(item, spider=None)
            files = list(Path(tmpdir, "posts").glob("*.md"))
            assert "how_i_learned_python" in files[0].stem

    def test_markdown_slug_collision_appends_number(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pipe = MarkdownExportPipeline(output_dir=tmpdir)
            pipe.open_spider(spider=None)
            post_dir = Path(tmpdir, "posts")
            post_dir.mkdir(parents=True, exist_ok=True)
            (post_dir / "reddit-how_i_learned_python.md").write_text("existing")

            item1 = PostItem(
                site="reddit",
                url="https://example.com/1",
                title="How I Learned Python!",
            )
            item2 = PostItem(
                site="reddit",
                url="https://example.com/2",
                title="How I Learned Python!",
            )
            pipe.process_item(item1, spider=None)
            pipe.process_item(item2, spider=None)

            files = [f.name for f in post_dir.glob("*.md")]
            assert "reddit-how_i_learned_python.md" in files
            assert "reddit-how_i_learned_python-2.md" in files

    def test_product_item_gets_product_listing_source_type(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pipe = MarkdownExportPipeline(output_dir=tmpdir)
            pipe.open_spider(spider=None)
            item = ProductItem(
                site="hotmart",
                url="https://hotmart.com/product/1",
                title="Test Product",
                price=29.99,
                currency="USD",
                rating=4.5,
                review_count=100,
                seller="Test Seller",
            )
            pipe.process_item(item, spider=None)
            files = list(Path(tmpdir, "products").glob("*.md"))
            content = files[0].read_text()
            assert "source_type: product_listing" in content
            assert "price: 29.99" in content


class TestChunkedJSONPipeline:
    def test_open_spider_creates_output_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pipe = ChunkedJSONPipeline(output_dir=tmpdir)
            pipe.open_spider(spider=None)
            assert Path(tmpdir, "chunks.jsonl").exists() is False

    def test_process_item_writes_jsonl_line(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pipe = ChunkedJSONPipeline(output_dir=tmpdir)
            pipe.open_spider(spider=None)
            item = PostItem(
                site="reddit",
                url="https://old.reddit.com/r/Python/comments/abc123",
                title="Test Title",
                content="Test content.",
                score=5,
                comment_count=3,
            )
            result = pipe.process_item(item, spider=None)
            pipe.close_spider(spider=None)
            assert result is item

            lines = Path(tmpdir, "chunks.jsonl").read_text().strip().split("\n")
            assert len(lines) == 1
            chunk = json.loads(lines[0])
            assert "chunk_id" in chunk
            assert chunk["chunk_id"].startswith("reddit-")
            assert len(chunk["chunk_id"].split("-")[1]) == 8
            assert chunk["text"].startswith("# Test Title")
            assert "Test content." in chunk["text"]
            assert chunk["metadata"]["site"] == "reddit"
            assert chunk["metadata"]["score"] == 5
            assert chunk["metadata"]["source_type"] == "social_media"
            assert "content" not in chunk["metadata"]

    def test_appends_multiple_lines(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pipe = ChunkedJSONPipeline(output_dir=tmpdir)
            pipe.open_spider(spider=None)
            pipe.process_item(PostItem(site="reddit", url="https://x.com/1", title="One"), spider=None)
            pipe.process_item(PostItem(site="reddit", url="https://x.com/2", title="Two"), spider=None)
            pipe.close_spider(spider=None)

            lines = Path(tmpdir, "chunks.jsonl").read_text().strip().split("\n")
            assert len(lines) == 2

    def test_content_none_handled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pipe = ChunkedJSONPipeline(output_dir=tmpdir)
            pipe.open_spider(spider=None)
            item = PostItem(
                site="reddit",
                url="https://x.com/1",
                title="No Content",
                content=None,
            )
            pipe.process_item(item, spider=None)
            pipe.close_spider(spider=None)

            lines = Path(tmpdir, "chunks.jsonl").read_text().strip().split("\n")
            chunk = json.loads(lines[0])
            assert chunk["text"] == "# No Content"
            assert "content" not in chunk["metadata"]

    def test_chunk_id_is_deterministic(self):
        pipe = ChunkedJSONPipeline()
        item = PostItem(site="reddit", url="https://same-url.com", title="Same")
        chunk_id1 = pipe._build_chunk(item)
        chunk_id2 = pipe._build_chunk(item)
        assert chunk_id1 == chunk_id2

    def test_generic_item_goes_to_pages_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pipe = MarkdownExportPipeline(output_dir=tmpdir)
            pipe.open_spider(spider=None)
            assert Path(tmpdir, "pages").exists()
            item = GenericItem(
                site="example.com",
                url="https://example.com/product",
                title="Test Product",
                page_type="product",
                price=29.99,
            )
            pipe.process_item(item, spider=None)
            files = list(Path(tmpdir, "pages").glob("*.md"))
            assert len(files) == 1
            content = files[0].read_text()
            assert "source_type: product" in content

    def test_generic_item_jsonl_source_type(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pipe = ChunkedJSONPipeline(output_dir=tmpdir)
            pipe.open_spider(spider=None)
            item = GenericItem(
                site="example.com",
                url="https://example.com/article",
                title="Test Article",
                page_type="article",
                content="Article body text here.",
            )
            pipe.process_item(item, spider=None)
            pipe.close_spider(spider=None)
            lines = Path(tmpdir, "chunks.jsonl").read_text().strip().split("\n")
            chunk = json.loads(lines[0])
            assert chunk["metadata"]["source_type"] == "article"
