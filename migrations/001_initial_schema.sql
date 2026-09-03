-- Migration 001: Initial schema for jobs table
-- Target Database: PostgreSQL

CREATE TABLE IF NOT EXISTS jobs (
    id VARCHAR(36) PRIMARY KEY,
    url TEXT NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'queued',
    stage VARCHAR(50) NOT NULL DEFAULT 'initialized',
    current_queue VARCHAR(50) DEFAULT 'scrape_queue',
    metadata_json JSONB,
    video_path TEXT,
    audio_path TEXT,
    transcription_json JSONB,
    error_message TEXT,
    transcription_provider VARCHAR(20) DEFAULT 'openai',
    webhook_url TEXT,
    webhook_status VARCHAR(30) DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_stage ON jobs(stage);

