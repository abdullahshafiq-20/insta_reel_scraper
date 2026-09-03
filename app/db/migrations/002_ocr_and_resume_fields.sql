-- Migration 002: Add OCR results, content_type, and resume tracking to jobs table
-- Target Database: PostgreSQL

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS content_type VARCHAR(20) DEFAULT 'reel';
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS ocr_json JSONB;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS resume_count INT DEFAULT 0;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS last_resumed_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_jobs_content_type ON jobs(content_type);

