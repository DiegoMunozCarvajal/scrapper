-- Supabase migration: per-spider tables
-- Generated 2026-07-16
-- Run in Supabase SQL Editor: https://app.supabase.com/project/_/sql

-- ═══════════════════════════════════════════════════════════════
-- Reddit (PostItem)
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS reddit (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    site TEXT,
    url TEXT NOT NULL,
    title TEXT,
    author TEXT,
    content TEXT,
    score INTEGER,
    comment_count INTEGER,
    published_at TIMESTAMPTZ,
    link_flair TEXT,
    domain TEXT,
    nsfw BOOLEAN DEFAULT FALSE,
    is_self_post BOOLEAN DEFAULT FALSE,
    permalink TEXT,
    quality_issues JSONB DEFAULT '[]'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb,
    scraped_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (site, url)
);

CREATE INDEX IF NOT EXISTS idx_reddit_published_at ON reddit (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_reddit_metadata_query ON reddit USING GIN ((metadata -> 'query'));
CREATE INDEX IF NOT EXISTS idx_reddit_metadata_subreddit ON reddit USING GIN ((metadata -> 'subreddit'));

-- ═══════════════════════════════════════════════════════════════
-- Stake (OddsItem)
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS stake (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    site TEXT,
    url TEXT NOT NULL,
    title TEXT,
    sport TEXT,
    league TEXT,
    tournament TEXT,
    match_date TEXT,
    commence_time TIMESTAMPTZ,
    player_a TEXT,
    player_b TEXT,
    odds_a NUMERIC(10,2),
    odds_b NUMERIC(10,2),
    surface TEXT DEFAULT 'hard',
    market_type TEXT DEFAULT 'moneyline',
    quality_issues JSONB DEFAULT '[]'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb,
    scraped_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (site, url)
);

CREATE INDEX IF NOT EXISTS idx_stake_commence_time ON stake (commence_time DESC);
CREATE INDEX IF NOT EXISTS idx_stake_player_a ON stake (player_a);
CREATE INDEX IF NOT EXISTS idx_stake_player_b ON stake (player_b);

-- ═══════════════════════════════════════════════════════════════
-- Pinnacle (OddsItem — same schema as stake)
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS pinnacle (LIKE stake INCLUDING ALL);

-- ═══════════════════════════════════════════════════════════════
-- Stake Results (OddsItem — same schema as stake)
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS stake_results (LIKE stake INCLUDING ALL);

-- ═══════════════════════════════════════════════════════════════
-- CoreTennis (TennisMatchItem)
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS coretennis (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    url TEXT NOT NULL,
    title TEXT,
    winner_name TEXT,
    loser_name TEXT,
    score TEXT,
    surface TEXT,
    tourney_date INTEGER,
    tourney_level TEXT,
    tourney_name TEXT,
    round TEXT,
    best_of TEXT,
    source_url TEXT,
    scraped_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (url)
);

CREATE INDEX IF NOT EXISTS idx_coretennis_tourney_date ON coretennis (tourney_date DESC);
CREATE INDEX IF NOT EXISTS idx_coretennis_winner ON coretennis (winner_name);
CREATE INDEX IF NOT EXISTS idx_coretennis_loser ON coretennis (loser_name);

-- ═══════════════════════════════════════════════════════════════
-- Hotmart (ProductItem)
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS hotmart (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    site TEXT,
    url TEXT NOT NULL,
    title TEXT,
    price NUMERIC(12,2),
    currency TEXT,
    rating NUMERIC(3,2),
    review_count INTEGER,
    seller TEXT,
    availability TEXT,
    quality_issues JSONB DEFAULT '[]'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb,
    scraped_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (site, url)
);

-- ═══════════════════════════════════════════════════════════════
-- Generic spiders (GenericItem — scraped_pages schema)
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS corte (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    site TEXT,
    url TEXT NOT NULL,
    page_type TEXT,
    title TEXT,
    content TEXT,
    price NUMERIC(12,2),
    currency TEXT,
    rating NUMERIC(3,2),
    review_count INTEGER,
    score INTEGER,
    author TEXT,
    image_url TEXT,
    category TEXT,
    published_at TIMESTAMPTZ,
    quality_issues JSONB DEFAULT '[]'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb,
    scraped_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (site, url)
);

CREATE TABLE IF NOT EXISTS rama (LIKE corte INCLUDING ALL);
CREATE TABLE IF NOT EXISTS generic (LIKE corte INCLUDING ALL);

-- ═══════════════════════════════════════════════════════════════
-- Optional: drop old tables once migration is verified
-- ═══════════════════════════════════════════════════════════════
-- DROP TABLE IF EXISTS posts;
-- DROP TABLE IF EXISTS products;
-- DROP TABLE IF EXISTS scraped_pages;
