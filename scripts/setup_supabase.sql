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
    quality_issues JSONB DEFAULT '[]',
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
    quality_issues JSONB DEFAULT '[]',
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

-- ── Row Level Security (RLS) ─────────────────────
ALTER TABLE posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE products ENABLE ROW LEVEL SECURITY;
ALTER TABLE sites ENABLE ROW LEVEL SECURITY;
ALTER TABLE scrape_jobs ENABLE ROW LEVEL SECURITY;

-- Public read access (anyone with project URL can read)
DO $$ BEGIN
    CREATE POLICY "Public can read posts" ON posts FOR SELECT USING (true);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE POLICY "Public can read products" ON products FOR SELECT USING (true);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE POLICY "Public can read sites" ON sites FOR SELECT USING (true);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Service role full access (for scraping pipeline)
DO $$ BEGIN
    CREATE POLICY "Service can do anything with posts" ON posts FOR ALL USING (true) WITH CHECK (true);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE POLICY "Service can do anything with products" ON products FOR ALL USING (true) WITH CHECK (true);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE POLICY "Service can do anything with sites" ON sites FOR ALL USING (true) WITH CHECK (true);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE POLICY "Service can do anything with scrape_jobs" ON scrape_jobs FOR ALL USING (true) WITH CHECK (true);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── Migrations (idempotent) ─────────────────────
-- Add quality_issues column if missing (v0.4+)
ALTER TABLE posts ADD COLUMN IF NOT EXISTS quality_issues JSONB DEFAULT '[]';
ALTER TABLE products ADD COLUMN IF NOT EXISTS quality_issues JSONB DEFAULT '[]';
