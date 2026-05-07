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
    thumbnail     TEXT,
    link_flair    TEXT,
    domain        TEXT,
    nsfw          BOOLEAN DEFAULT FALSE,
    is_self_post  BOOLEAN DEFAULT FALSE,
    permalink     TEXT,
    quality_issues JSONB DEFAULT '[]',
    metadata      JSONB DEFAULT '{}',
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
    scraped_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(site, url)
);

-- ── Generic scraped pages (LLM extraction) ─────────
CREATE TABLE IF NOT EXISTS scraped_pages (
    id            BIGSERIAL PRIMARY KEY,
    site          TEXT NOT NULL DEFAULT 'generic',
    url           TEXT NOT NULL,
    page_type     TEXT,
    title         TEXT,
    content       TEXT,
    price         DECIMAL(12,2),
    currency      TEXT DEFAULT 'USD',
    rating        DECIMAL(3,2),
    review_count  INTEGER DEFAULT 0,
    score         INTEGER DEFAULT 0,
    author        TEXT,
    published_at  TEXT,
    quality_issues JSONB DEFAULT '[]',
    metadata      JSONB DEFAULT '{}',
    scraped_at    TIMESTAMPTZ DEFAULT NOW(),
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(site, url)
);

-- ── Indexes ─────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_posts_site ON posts(site);
CREATE INDEX IF NOT EXISTS idx_posts_scraped_at ON posts(scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_products_site ON products(site);
CREATE INDEX IF NOT EXISTS idx_products_price ON products(price);
CREATE INDEX IF NOT EXISTS idx_products_scraped_at ON products(scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_scraped_pages_type ON scraped_pages (page_type);
CREATE INDEX IF NOT EXISTS idx_scraped_pages_site ON scraped_pages (site);
CREATE INDEX IF NOT EXISTS idx_scraped_pages_scraped_at ON scraped_pages (scraped_at DESC);


-- ── Row Level Security (RLS) ─────────────────────
ALTER TABLE posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE products ENABLE ROW LEVEL SECURITY;
ALTER TABLE scraped_pages ENABLE ROW LEVEL SECURITY;
ALTER TABLE sites ENABLE ROW LEVEL SECURITY;

-- Public read access (only via anon/authenticated roles)
DO $$ BEGIN
    DROP POLICY IF EXISTS "Public can read posts" ON posts;
    CREATE POLICY "Public can read posts" ON posts FOR SELECT TO anon, authenticated USING (true);
END $$;

DO $$ BEGIN
    DROP POLICY IF EXISTS "Public can read products" ON products;
    CREATE POLICY "Public can read products" ON products FOR SELECT TO anon, authenticated USING (true);
END $$;

DO $$ BEGIN
    DROP POLICY IF EXISTS "Public can read scraped_pages" ON scraped_pages;
    CREATE POLICY "Public can read scraped_pages" ON scraped_pages FOR SELECT TO anon, authenticated USING (true);
END $$;

DO $$ BEGIN
    DROP POLICY IF EXISTS "Public can read sites" ON sites;
    CREATE POLICY "Public can read sites" ON sites FOR SELECT TO anon, authenticated USING (true);
END $$;

-- Service role full access (for scraping pipeline)
DO $$ BEGIN
    DROP POLICY IF EXISTS "Service can do anything with posts" ON posts;
    CREATE POLICY "Service can do anything with posts" ON posts FOR ALL TO service_role USING (true) WITH CHECK (true);
END $$;

DO $$ BEGIN
    DROP POLICY IF EXISTS "Service can do anything with products" ON products;
    CREATE POLICY "Service can do anything with products" ON products FOR ALL TO service_role USING (true) WITH CHECK (true);
END $$;

DO $$ BEGIN
    DROP POLICY IF EXISTS "Service can do anything with scraped_pages" ON scraped_pages;
    CREATE POLICY "Service can do anything with scraped_pages" ON scraped_pages FOR ALL TO service_role USING (true) WITH CHECK (true);
END $$;

DO $$ BEGIN
    DROP POLICY IF EXISTS "Service can do anything with sites" ON sites;
    CREATE POLICY "Service can do anything with sites" ON sites FOR ALL TO service_role USING (true) WITH CHECK (true);
END $$;

-- ── Migrations (idempotent) ─────────────────────
-- Add quality_issues column if missing (v0.4+)
ALTER TABLE posts ADD COLUMN IF NOT EXISTS quality_issues JSONB DEFAULT '[]';
ALTER TABLE products ADD COLUMN IF NOT EXISTS quality_issues JSONB DEFAULT '[]';

-- Add image_url and category columns (v0.5+)
ALTER TABLE scraped_pages ADD COLUMN IF NOT EXISTS image_url TEXT;
ALTER TABLE scraped_pages ADD COLUMN IF NOT EXISTS category TEXT;

-- Add Reddit metadata columns emitted by PostItem (v0.6+)
-- thumbnail removed (v0.8+)
ALTER TABLE posts ADD COLUMN IF NOT EXISTS link_flair TEXT;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS domain TEXT;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS nsfw BOOLEAN DEFAULT FALSE;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS is_self_post BOOLEAN DEFAULT FALSE;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS permalink TEXT;

-- ── Distributed locks for Cloud Run Jobs (v0.7+) ─────────────────────
CREATE TABLE IF NOT EXISTS spider_locks (
    spider        TEXT PRIMARY KEY,
    locked_at     TIMESTAMPTZ,
    locked_until  TIMESTAMPTZ,
    status        TEXT DEFAULT 'running',
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE spider_locks ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    DROP POLICY IF EXISTS "Service can do anything with spider_locks" ON spider_locks;
    CREATE POLICY "Service can do anything with spider_locks" ON spider_locks FOR ALL TO service_role USING (true) WITH CHECK (true);
END $$;

-- Función RPC atómica para adquirir lock (evita race conditions)
CREATE OR REPLACE FUNCTION acquire_spider_lock(
    p_spider TEXT,
    p_locked_at TIMESTAMPTZ,
    p_locked_until TIMESTAMPTZ
) RETURNS BOOLEAN AS $$
BEGIN
    -- Limpiar locks expirados
    DELETE FROM spider_locks WHERE locked_until < NOW();

    -- Intentar insertar
    BEGIN
        INSERT INTO spider_locks (spider, locked_at, locked_until, status)
        VALUES (p_spider, p_locked_at, p_locked_until, 'running');
        RETURN TRUE;
    EXCEPTION WHEN unique_violation THEN
        RETURN FALSE;
    END;
END;
$$ LANGUAGE plpgsql;
