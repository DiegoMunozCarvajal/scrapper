# Graph Report - .  (2026-05-03)

## Corpus Check
- Corpus is ~44,679 words - fits in a single context window. You may not need a graph.

## Summary
- 618 nodes · 951 edges · 32 communities detected
- Extraction: 71% EXTRACTED · 29% INFERRED · 0% AMBIGUOUS · INFERRED: 272 edges (avg confidence: 0.69)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Items & Validation Pipeline|Items & Validation Pipeline]]
- [[_COMMUNITY_Extensions EmailAlerter & StatsLogger|Extensions: EmailAlerter & StatsLogger]]
- [[_COMMUNITY_Hotmart Spider & Price Parsing|Hotmart Spider & Price Parsing]]
- [[_COMMUNITY_Architecture & Design Docs|Architecture & Design Docs]]
- [[_COMMUNITY_RAG Export Pipelines|RAG Export Pipelines]]
- [[_COMMUNITY_LLM Cache & Extractor|LLM Cache & Extractor]]
- [[_COMMUNITY_AGENTS.md Spider Catalog|AGENTS.md Spider Catalog]]
- [[_COMMUNITY_Scrapy Middlewares|Scrapy Middlewares]]
- [[_COMMUNITY_Reddit Spider & RSS Parsing|Reddit Spider & RSS Parsing]]
- [[_COMMUNITY_Core Modules Overview|Core Modules Overview]]
- [[_COMMUNITY_Stealth & Anti-Bot Handlers|Stealth & Anti-Bot Handlers]]
- [[_COMMUNITY_Metrics Dashboard|Metrics Dashboard]]
- [[_COMMUNITY_Settings Configuration|Settings Configuration]]
- [[_COMMUNITY_Amazon Spider (Deprecated)|Amazon Spider (Deprecated)]]
- [[_COMMUNITY_Data Models (PostProduct)|Data Models (Post/Product)]]
- [[_COMMUNITY_Spider & Prompt Names|Spider & Prompt Names]]
- [[_COMMUNITY_Colombian Politics (Reddit RAG)|Colombian Politics (Reddit RAG)]]
- [[_COMMUNITY_Integration Test Fixtures|Integration Test Fixtures]]
- [[_COMMUNITY_Supabase Pipeline|Supabase Pipeline]]
- [[_COMMUNITY_Supabase Integration Tests|Supabase Integration Tests]]
- [[_COMMUNITY_Anti-Bot Handler Module|Anti-Bot Handler Module]]
- [[_COMMUNITY_Monitoring Extensions Cluster|Monitoring Extensions Cluster]]
- [[_COMMUNITY_Docker & README|Docker & README]]
- [[_COMMUNITY_Spiders Package Init|Spiders Package Init]]
- [[_COMMUNITY_Error Alerter & Hetzner|Error Alerter & Hetzner]]
- [[_COMMUNITY_Proxy & UA Middlewares|Proxy & UA Middlewares]]
- [[_COMMUNITY_Misc Reddit Posts|Misc Reddit Posts]]
- [[_COMMUNITY_Stats Logger Agent|Stats Logger Agent]]
- [[_COMMUNITY_Scraper Status Table|Scraper Status Table]]
- [[_COMMUNITY_Retry Middleware|Retry Middleware]]
- [[_COMMUNITY_ScrapeResult Model|ScrapeResult Model]]
- [[_COMMUNITY_RAG Export Format|RAG Export Format]]

## God Nodes (most connected - your core abstractions)
1. `PostItem` - 52 edges
2. `ProductItem` - 33 edges
3. `StatsLogger` - 26 edges
4. `EmailAlerter` - 23 edges
5. `FakeSpider` - 22 edges
6. `DataQualityPipeline` - 20 edges
7. `HotmartSpider` - 17 edges
8. `TestDataQualityPipeline` - 17 edges
9. `MarkdownExportPipeline` - 17 edges
10. `ChunkedJSONPipeline` - 16 edges

## Surprising Connections (you probably didn't know these)
- `DataQualityPipeline` --shares_data_with--> `StatsLogger Metrics Persistence`  [INFERRED]
  src/scrapper/pipelines.py → docs/superpowers/specs/2026-05-02-monitoring-rag-export-design.md
- `DedupInMemoryPipeline` --semantically_similar_to--> `SupabaseSchema`  [INFERRED] [semantically similar]
  src/scrapper/pipelines.py → scripts/setup_supabase.sql
- `CurlCffiDownloadHandler` --conceptually_related_to--> `Canvas/WebGL Fingerprint Spoofing`  [INFERRED]
  src/scrapper/curl_cffi_handler.py → docs/superpowers/specs/2026-05-03-llm-fallback-antibot-design.md
- `test_post_item_creation()` --calls--> `PostItem`  [INFERRED]
  tests/unit/test_items.py → src/scrapper/items.py
- `test_post_item_defaults()` --calls--> `PostItem`  [INFERRED]
  tests/unit/test_items.py → src/scrapper/items.py

## Hyperedges (group relationships)
- **Scrape metrics collection, visualization, and alerting lifecycle** — stats_logger, metrics_dashboard, email_alerter, metrics_json [EXTRACTED 1.00]
- **LLM extraction fallback when DOM selectors yield no results** — reddit_spider, hotmart_spider, llm_extractor [EXTRACTED 1.00]
- **Dual-format RAG export pipeline for vector database ingestion** — markdown_export, chunked_json_export, post_item, product_item [EXTRACTED 1.00]
- **Triple Strategy Extraction Flow (primary→fallback→LLM)** — spiders_triple_strategy, spiders_RedditSpider, spiders_HotmartSpider, llm_extractor_llm_fallback [INFERRED 0.85]
- **Multi-Layer Anti-Detection Stack** — stealth_handler_human_simulation, curl_cffi_handler_tls_impersonation, stealth_handler_cookie_persistence, settings_DOWNLOAD_HANDLERS [INFERRED 0.80]
- **Dual-Format RAG Export (Markdown + JSONL)** — rag_export_MarkdownExportPipeline, rag_export_ChunkedJSONPipeline, rag_export_rag_format, items_PostItem [EXTRACTED 1.00]
- **Metrics → Dashboard Pipeline** — stats_logger_metrics, metrics_dashboard_extension, dashboard_template, dashboard_generated [EXTRACTED 1.00]
- **RAG Export Pipeline (items → .md + .jsonl)** — markdown_export_pipeline, chunked_jsonl_pipeline, colombia_reddit_communities, testosterone_discussion, rorschach_comic [EXTRACTED 0.95]
- **Anti-Bot Hardening Suite** — curl_cffi_handler, stealth_canvas_webgl_spoof, human_simulation_scroll, cookie_persistence [EXTRACTED 1.00]

## Communities

### Community 0 - "Items & Validation Pipeline"
Cohesion: 0.06
Nodes (30): TestProductItemDefaults, TestPostItemFields, TestRedditPostItemFromRSS, TestRedditRSSParsing, PostItem, ProductItem, DataQualityPipeline, DedupInMemoryPipeline (+22 more)

### Community 1 - "Extensions: EmailAlerter & StatsLogger"
Cohesion: 0.07
Nodes (18): EmailAlerter, ErrorAlerter, Scrapy extensions for monitoring and alerting., Log scraping stats at spider completion., Send email alerts on critical errors and metric anomalies., Log scraping stats at spider completion and persist to metrics.json., POST to a webhook URL when a spider encounters critical errors., _setup_log_rotation() (+10 more)

### Community 2 - "Hotmart Spider & Price Parsing"
Cohesion: 0.04
Nodes (22): TestHotmartAPIResponseParsing, TestParsePrice, TestParseReviewCount, TestHotmartLLMFallback, # NOTE: Use str.replace("{html}", html) instead of .format() — the JSON, FakeFailure, Minimal failure-like object for errback/fallback dispatch., _click_load_more() (+14 more)

### Community 3 - "Architecture & Design Docs"
Cohesion: 0.05
Nodes (53): AGENTS.md - Project Guidance, API Interception Primary Strategy (Hotmart), Asyncio Deadlock Fix (run_until_complete → PageMethod), ChunkedJSONPipeline, ChunkedJSONPipeline (vector DB JSONL chunks), Cookie Persistence Between Runs, CurlCffiDownloadHandler, Generated Metrics Dashboard (+45 more)

### Community 4 - "RAG Export Pipelines"
Cohesion: 0.08
Nodes (14): ChunkedJSONPipeline, MarkdownExportPipeline, _needs_quoting(), Convert each scraped item to a Markdown file with YAML frontmatter., Export items as JSONL chunks optimized for vector DB ingestion., ensure_dir(), random_user_agent(), slugify() (+6 more)

### Community 5 - "LLM Cache & Extractor"
Cohesion: 0.07
Nodes (21): # NOTE: Use str.replace("{html}", html) instead of .format() — the JSON, LLMCache, Initialize the cache with a database path and TTL in seconds., Retrieve a cached value by key, returning None if missing or expired., Store a value under the given key, overwriting any existing entry., Close the underlying database connection., SQLite-backed key-value cache with TTL expiry, thread-safe access, and context m, llm_fallback() (+13 more)

### Community 6 - "AGENTS.md Spider Catalog"
Cohesion: 0.08
Nodes (32): AmazonSpider (Deprecated), DedupInMemoryPipeline, HotmartSpider, MercadoLibreSpider (Deprecated), playwright-stealth v2, PostItem, ProductItem, ProxyRotationMiddleware (+24 more)

### Community 7 - "Scrapy Middlewares"
Cohesion: 0.12
Nodes (14): RetryMiddleware, ProxyRotationMiddleware, Custom Scrapy downloader middlewares for reliability and anti-bot., Retry on errors with exponential backoff: 1s, 2s, 4s, 8s., Rotate through proxy list on each request, including Playwright., Rotate user agent on each request., RetryWithBackoffMiddleware, UARotationMiddleware (+6 more)

### Community 8 - "Reddit Spider & RSS Parsing"
Cohesion: 0.13
Nodes (6): _make_reddit_spider(), TestRedditLLMFallback, Fallback: old.reddit.com search results (Strategy 2)., Extract full post content from detail page., RedditSpider, TestRedditSpider

### Community 9 - "Core Modules Overview"
Cohesion: 0.1
Nodes (28): PostItem, ProductItem, LLMCache (SQLite TTL cache), LLMExtractor, llm_fallback (shared LLM fallback function), LLM Extraction Strategy (HTML chunking + JSON mode + caching), Post (dataclass model), Product (dataclass model) (+20 more)

### Community 10 - "Stealth & Anti-Bot Handlers"
Cohesion: 0.08
Nodes (9): TestStealthHandlerConfig, CurlCffiDownloadHandler, Custom Scrapy download handler using playwright-stealth v2., Playwright download handler with playwright-stealth v2 patches., Playwright download handler with playwright-stealth v2 patches., ScrapyPlaywrightStealthDownloadHandler, ScrapyPlaywrightDownloadHandler, ScrapyPlaywrightStealthDownloadHandler (+1 more)

### Community 11 - "Metrics Dashboard"
Cohesion: 0.15
Nodes (7): _get_template(), MetricsDashboard, Generate a local HTML dashboard from persisted crawl metrics., Generate dashboard.html from metrics.json after each crawl., FakeCrawler, FakeSpider, TestMetricsDashboard

### Community 12 - "Settings Configuration"
Cohesion: 0.12
Nodes (1): TestSettings

### Community 13 - "Amazon Spider (Deprecated)"
Cohesion: 0.18
Nodes (3): AmazonSpider, Follow product URL to extract description + seller info., Follow product URL to extract description + seller info.

### Community 14 - "Data Models (Post/Product)"
Cohesion: 0.36
Nodes (4): Post, Product, ScrapeResult, TestModels

### Community 15 - "Spider & Prompt Names"
Cohesion: 0.29
Nodes (8): HOTMART_PROMPT, HotmartSpider, LLMCache, LLMExtractor, _parse_price, _parse_review_count, REDDIT_PROMPT, RedditSpider

### Community 16 - "Colombian Politics (Reddit RAG)"
Cohesion: 0.25
Nodes (8): 2026 Colombian Presidential Election, Colombian Reddit Communities (r/Colombia, r/ColombiaReddit, r/Republica_Colombia), FARC Assassination of Ivan Cepeda's Father, Invamer Polling Firm, Ivan Cepeda (Colombian Political Candidate), Mandatory vs Voluntary Military Service Debate (Colombia), Petro Government Pension/Subsidy Fund Claims, Polymarket Prediction Market

### Community 18 - "Integration Test Fixtures"
Cohesion: 0.33
Nodes (1): Shared fixtures for integration tests.

### Community 19 - "Supabase Pipeline"
Cohesion: 0.33
Nodes (3): Upsert items into Supabase Postgres tables., Upsert items into Supabase Postgres tables., SupabasePipeline

### Community 20 - "Supabase Integration Tests"
Cohesion: 0.33
Nodes (1): TestSupabaseIntegration

### Community 21 - "Anti-Bot Handler Module"
Cohesion: 0.4
Nodes (6): CurlCffiDownloadHandler, TLS Impersonation (curl-cffi chrome124), Composite Download Handler Chain, ScrapyPlaywrightStealthDownloadHandler, Cookie Persistence (per-context JSON files), Human Simulation (scroll/delay + canvas/WebGL spoofing)

### Community 22 - "Monitoring Extensions Cluster"
Cohesion: 0.4
Nodes (5): MetricsDashboard, EmailAlerter, StatsLogger, Anomaly Detection (items drop >50% vs historical avg), Metrics Persistence (JSON + portalocker locking + corruption recovery)

### Community 24 - "Docker & README"
Cohesion: 0.67
Nodes (3): Scrapyd, ScrapydWeb, Scrapper Project

### Community 26 - "Spiders Package Init"
Cohesion: 1.0
Nodes (1): Scrapy spiders for multi-site scraping.

### Community 27 - "Error Alerter & Hetzner"
Cohesion: 1.0
Nodes (2): ErrorAlerter, Hetzner VPS

### Community 28 - "Proxy & UA Middlewares"
Cohesion: 1.0
Nodes (2): ProxyRotationMiddleware, UARotationMiddleware

### Community 29 - "Misc Reddit Posts"
Cohesion: 1.0
Nodes (2): Rorschach Test Comic Post (r/comics), Testosterone/Bodybuilding Discussion (r/moreplatesmoredates)

### Community 35 - "Stats Logger Agent"
Cohesion: 1.0
Nodes (1): StatsLogger

### Community 36 - "Scraper Status Table"
Cohesion: 1.0
Nodes (1): Spider Status Classification

### Community 39 - "Retry Middleware"
Cohesion: 1.0
Nodes (1): RetryWithBackoffMiddleware

### Community 40 - "ScrapeResult Model"
Cohesion: 1.0
Nodes (1): ScrapeResult (aggregator dataclass)

### Community 41 - "RAG Export Format"
Cohesion: 1.0
Nodes (1): RAG Export Pattern (Markdown + JSONL chunks for vector DBs)

## Knowledge Gaps
- **105 isolated node(s):** `Shared fixtures for integration tests.`, `Custom Scrapy download handler using playwright-stealth v2.`, `Playwright download handler with playwright-stealth v2 patches.`, `Custom Scrapy downloader middlewares for reliability and anti-bot.`, `Retry on errors with exponential backoff: 1s, 2s, 4s, 8s.` (+100 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Settings Configuration`** (17 nodes): `test_settings.py`, `test_dashboard_extension_registered()`, `test_metrics_dir_default()`, `test_metrics_max_runs_default()`, `test_rag_export_settings_exist()`, `test_rag_pipelines_registered()`, `TestSettings`, `.test_autothrottle_enabled()`, `.test_bot_name()`, `.test_concurrent_requests()`, `.test_download_delay()`, `.test_downloader_middlewares()`, `.test_item_pipelines()`, `.test_playwright_enabled()`, `.test_retry_enabled()`, `.test_robotstxt_obey()`, `.test_spider_modules()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Integration Test Fixtures`** (6 nodes): `hotmart_api_json()`, `hotmart_search_html()`, `Shared fixtures for integration tests.`, `reddit_rss()`, `reddit_search_html()`, `conftest.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Supabase Integration Tests`** (6 nodes): `TestSupabaseIntegration`, `.test_connection_succeeds()`, `.test_posts_table_exists()`, `.test_products_table_exists()`, `.test_upsert_and_read_post()`, `test_supabase.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Spiders Package Init`** (2 nodes): `Scrapy spiders for multi-site scraping.`, `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Error Alerter & Hetzner`** (2 nodes): `ErrorAlerter`, `Hetzner VPS`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Proxy & UA Middlewares`** (2 nodes): `ProxyRotationMiddleware`, `UARotationMiddleware`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Misc Reddit Posts`** (2 nodes): `Rorschach Test Comic Post (r/comics)`, `Testosterone/Bodybuilding Discussion (r/moreplatesmoredates)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Stats Logger Agent`** (1 nodes): `StatsLogger`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Scraper Status Table`** (1 nodes): `Spider Status Classification`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Retry Middleware`** (1 nodes): `RetryWithBackoffMiddleware`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `ScrapeResult Model`** (1 nodes): `ScrapeResult (aggregator dataclass)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `RAG Export Format`** (1 nodes): `RAG Export Pattern (Markdown + JSONL chunks for vector DBs)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `PostItem` connect `Items & Validation Pipeline` to `Reddit Spider & RSS Parsing`, `Supabase Pipeline`, `RAG Export Pipelines`?**
  _High betweenness centrality (0.073) - this node is a cross-community bridge._
- **Why does `ProductItem` connect `Items & Validation Pipeline` to `Reddit Spider & RSS Parsing`, `Hotmart Spider & Price Parsing`, `RAG Export Pipelines`, `Amazon Spider (Deprecated)`?**
  _High betweenness centrality (0.068) - this node is a cross-community bridge._
- **Why does `RedditSpider` connect `Reddit Spider & RSS Parsing` to `Items & Validation Pipeline`, `Hotmart Spider & Price Parsing`, `LLM Cache & Extractor`?**
  _High betweenness centrality (0.035) - this node is a cross-community bridge._
- **Are the 49 inferred relationships involving `PostItem` (e.g. with `FakeSpider` and `test_validate_drops_missing_url()`) actually correct?**
  _`PostItem` has 49 INFERRED edges - model-reasoned connections that need verification._
- **Are the 30 inferred relationships involving `ProductItem` (e.g. with `FakeSpider` and `test_product_item_creation()`) actually correct?**
  _`ProductItem` has 30 INFERRED edges - model-reasoned connections that need verification._
- **Are the 19 inferred relationships involving `StatsLogger` (e.g. with `FakeCrawler` and `FakeSpider`) actually correct?**
  _`StatsLogger` has 19 INFERRED edges - model-reasoned connections that need verification._
- **Are the 16 inferred relationships involving `EmailAlerter` (e.g. with `FakeCrawler` and `FakeSpider`) actually correct?**
  _`EmailAlerter` has 16 INFERRED edges - model-reasoned connections that need verification._