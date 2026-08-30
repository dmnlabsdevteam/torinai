-- Migration: fix_frontier_foresight_columns
-- Adds columns expected by frontier_foresight_methods_impl.py that were
-- missing from the original schema definitions.

-- research_publications: add capability + published_date
ALTER TABLE unified.research_publications
    ADD COLUMN IF NOT EXISTS capability VARCHAR(255) NULL,
    ADD COLUMN IF NOT EXISTS published_date TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS abstract TEXT NULL;

CREATE INDEX IF NOT EXISTS idx_research_publications_capability
    ON unified.research_publications(capability);

CREATE INDEX IF NOT EXISTS idx_research_publications_published_date
    ON unified.research_publications(published_date DESC);

-- benchmark_history: add capability + measured_at (mirrors timestamp) + model_version
ALTER TABLE unified.benchmark_history
    ADD COLUMN IF NOT EXISTS capability VARCHAR(255) NULL,
    ADD COLUMN IF NOT EXISTS measured_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS model_version VARCHAR(100) NULL;

-- Backfill measured_at from existing timestamp column so existing rows are queryable
UPDATE unified.benchmark_history
    SET measured_at = timestamp
    WHERE measured_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_benchmark_history_capability
    ON unified.benchmark_history(capability);

CREATE INDEX IF NOT EXISTS idx_benchmark_history_measured_at
    ON unified.benchmark_history(measured_at DESC);
