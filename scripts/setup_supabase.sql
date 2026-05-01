-- scripts/setup_supabase.sql
-- Run this in Supabase SQL Editor: https://supabase.com/dashboard > SQL Editor

-- ── Lookup table for known target sites ──────────────
CREATE TABLE IF NOT EXISTS sites (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,
    type        TEXT NOT NULL CHECK (type IN ('post', 'product')),
    base_url    TEXT NOT NULL,
    active      BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO sites (name, type, base_url) VALUES
    ('reddit', 'post', 'https://old.reddit.com'),
    ('quora', 'post', 'https://www.quora.com'),
    ('amazon', 'product', 'https://www.amazon.com'),
    ('mercadolibre', 'product', 'https://listado.mercadolibre.com.co'),
    ('hotmart', 'product', 'https://hotmart.com')
ON CONFLICT (name) DO NOTHING;

-- ── Scrape job tracking ─────────────────────────────
CREATE TABLE IF NOT EXISTS scrape_jobs (
    id            BIGSERIAL PRIMARY KEY,
    site_id       INTEGER REFERENCES sites(id),
    query         TEXT NOT NULL,
    status        TEXT DEFAULT 'pending' CHECK (status IN ('pending','running','done','failed')),
    items_scraped INTEGER DEFAULT 0,
    error_message TEXT,
    started_at    TIMESTAMPTZ,
    completed_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- ── Social / Q&A posts ──────────────────────────────
CREATE TABLE IF NOT EXISTS posts (
    id            BIGSERIAL PRIMARY KEY,
    site          TEXT NOT NULL,
    url           TEXT NOT NULL,
    title         TEXT,
    author        TEXT,
    content       TEXT,
    score         INTEGER DEFAULT 0,
    comment_count INTEGER DEFAULT 0,
    published_at  TIMESTAMPTZ,
    metadata      JSONB DEFAULT '{}',
    scrape_job_id INTEGER REFERENCES scrape_jobs(id),
    scraped_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(site, url)
);

-- ── E-commerce products ─────────────────────────────
CREATE TABLE IF NOT EXISTS products (
    id            BIGSERIAL PRIMARY KEY,
    site          TEXT NOT NULL,
    url           TEXT NOT NULL,
    title         TEXT,
    price         DECIMAL(12,2),
    currency      TEXT DEFAULT 'USD',
    rating        DECIMAL(3,2),
    review_count  INTEGER DEFAULT 0,
    seller        TEXT,
    availability  TEXT,
    metadata      JSONB DEFAULT '{}',
    scrape_job_id INTEGER REFERENCES scrape_jobs(id),
    scraped_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(site, url)
);

-- ── Indexes ─────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_posts_site ON posts(site);
CREATE INDEX IF NOT EXISTS idx_posts_scraped_at ON posts(scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_products_site ON products(site);
CREATE INDEX IF NOT EXISTS idx_products_price ON products(price);
CREATE INDEX IF NOT EXISTS idx_products_scraped_at ON products(scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_scrape_jobs_status ON scrape_jobs(status);