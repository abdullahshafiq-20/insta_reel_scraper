# Product Requirements Document (PRD)
## Instagram Reel/Post Scraper & Transcription Processing Engine

---

## 1. Executive Summary
The **Instagram Reel/Post Scraper & Transcription Processing Engine** is a staged, asynchronous API service designed to ingest Instagram Reel/Post URLs, extract comprehensive metadata, download the media, deterministically convert video to high-quality audio locally, and transcribe the spoken content using a switchable transcription backend (Local Whisper or OpenAI Whisper API).

Throughout the job lifecycle, the service persists status changes and sends real-time event updates to an external webhook URL.

---

## 2. Goals & Key Requirements
- **Asynchronous Job Pipeline**: The API immediately returns a `job_id` upon ingestion. Long-running tasks (scraping, audio conversion, transcription) execute in the background.
- **Multi-Stage Processing**:
  1. **Stage 1 (Metadata Extraction)**: Scrapes author, caption, stats (likes, comments, shares), tags, and video CDN URL.
  2. **Stage 2 (Local Audio Extraction)**: Downloads video stream and extracts clean 16kHz mono audio via FFmpeg locally and deterministically.
  3. **Stage 3 (Switchable Transcription)**: Transcribes the extracted audio using either a **Local Engine** (e.g., `faster-whisper` / `whisper`) or **OpenAI API** (`whisper-1` / `gpt-4o-audio`) based on environment configuration or per-job overrides.
- **Webhook Notifications**: Dispatches stage-by-stage progress and completion payloads to `WEBHOOK_URL`.
- **API Security**: All endpoints protected via API Key (`X-API-Key` or `?api_key=`).
- **Persistence & Auditing**: Database tracking for all job states, execution timestamps, retry counts, errors, and output artifacts.

---

## 3. High-Level Architecture & Lifecycle Flow

```
[ Client ] 
    │ (POST /api/v1/jobs with Reel URL + API Key)
    ▼
[ FastAPI Gateway / Auth ] ──► Return { job_id: "...", status: "queued" }
    │
    ▼
[ Database (Job Record Initialized) ]
    │
    ▼
[ Job Worker / Queue Manager ]
    │
    ├──► STAGE 1: METADATA EXTRACTION
    │       - Scrape Instagram DOM / Meta / JSON (No login required)
    │       - Save metadata (username, caption, stats, video_url)
    │       - Emit Webhook: stage="metadata_extracted"
    │
    ├──► STAGE 2: MEDIA & AUDIO CONVERSION (Local & Deterministic)
    │       - Download progressive MP4 video
    │       - Extract 16kHz WAV/MP3 audio via FFmpeg
    │       - Emit Webhook: stage="audio_converted"
    │
    ├──► STAGE 3: TRANSCRIPTION (Switchable)
    │       - IF provider == "local": Process via local Faster-Whisper
    │       - IF provider == "openai": Dispatch to OpenAI Whisper API
    │       - Extract full text, segments, timestamps, language
    │       - Emit Webhook: stage="transcribed"
    │
    └──► STAGE 4: COMPLETION & AGGREGATION
            - Aggregate all data (Metadata + Video URL + Transcript)
            - Update DB status to "completed"
            - Emit Final Webhook: status="completed"
```

---

## 4. Detailed Stage Specifications

### Stage 1: Ingestion & Validation
- Validates Instagram Reel / Post URL format.
- Generates a unique `job_id` (UUIDv4).
- Creates an entry in the database with status `queued`.
- Emits immediate HTTP 202 Accepted response to client.

### Stage 2: Metadata Scraping
- Utilizes headless Playwright engine.
- Extracts:
  - Shortcode & Canonical URL
  - Creator Username
  - Full Caption, Hashtags (`#`), Mentions (`@`)
  - Engagement Metrics (Like count, Comment count, Share count)
  - Progressive MP4 CDN stream URL
- Updates job state in DB (`stage=metadata_extracted`).

### Stage 3: Media Download & Local Audio Extraction
- Deterministic and completely local processing.
- Downloads progressive MP4 stream directly to isolated temporary workspace.
- Executes FFmpeg pipeline to produce normalized mono 16kHz audio:
  `ffmpeg -y -i input.mp4 -vn -acodec pcm_s16le -ar 16000 -ac 1 output.wav`
- Updates job state in DB (`stage=audio_converted`).

### Stage 4: Transcription (Switchable Engine)
The transcription layer is abstracted via a common interface (`BaseTranscriptionService`), supporting:
1. **Local Provider (`TRANSCRIPTION_PROVIDER=local`)**:
   - Uses `faster-whisper` / `whisper` model (configurable size: `tiny`, `base`, `small`, `medium`, `large-v3`).
   - Runs locally without external API costs or internet dependency.
2. **OpenAI Provider (`TRANSCRIPTION_PROVIDER=openai`)**:
   - Calls OpenAI Whisper API using `OPENAI_API_KEY`.
   - Returns high-accuracy transcription with punctuation, timestamps, and language detection.

### Stage 5: Webhook Dispatcher
- Dispatches HTTP POST requests to the configured `WEBHOOK_URL`.
- Configurable retry policy with exponential backoff.
- Delivers granular stage updates (`job.created`, `job.stage_updated`, `job.completed`, `job.failed`).

---

## 5. API Interface Specifications

### 5.1 Endpoints

#### 1. Submit Job
- **Route**: `POST /api/v1/jobs`
- **Headers**: `X-API-Key: <YOUR_API_KEY>`
- **Request Body**:
```json
{
  "url": "https://www.instagram.com/reel/DE48s0_vG4v/",
  "transcription_provider": "openai", // Optional: "local" | "openai" (defaults to env)
  "webhook_url": "https://client-domain.com/webhook" // Optional: overrides env WEBHOOK_URL
}
```
- **Response (202 Accepted)**:
```json
{
  "success": true,
  "job_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "status": "queued",
  "stage": "initialized",
  "created_at": "2026-09-01T14:30:00Z"
}
```

#### 2. Get Job Status & Result
- **Route**: `GET /api/v1/jobs/{job_id}`
- **Headers**: `X-API-Key: <YOUR_API_KEY>`
- **Response (200 OK - In Progress)**:
```json
{
  "success": true,
  "job_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "status": "processing",
  "stage": "audio_converted",
  "progress_percentage": 60,
  "created_at": "2026-09-01T14:30:00Z",
  "updated_at": "2026-09-01T14:30:15Z"
}
```
- **Response (200 OK - Completed)**:
```json
{
  "success": true,
  "job_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "status": "completed",
  "stage": "finished",
  "data": {
    "metadata": {
      "shortcode": "DE48s0_vG4v",
      "url": "https://www.instagram.com/reel/DE48s0_vG4v/",
      "username": "creator_name",
      "caption": "Check out this reel! #nature #travel",
      "hashtags": ["nature", "travel"],
      "mentions": [],
      "like_count": "15.4K",
      "comment_count": "320",
      "share_count": "890",
      "video_url": "https://instagram.fdel...mp4"
    },
    "transcription": {
      "provider": "openai",
      "language": "en",
      "duration_seconds": 24.5,
      "text": "Welcome to our latest adventure exploring the hidden mountain waterfalls.",
      "segments": [
        {
          "id": 0,
          "start": 0.0,
          "end": 4.2,
          "text": "Welcome to our latest adventure"
        },
        {
          "id": 1,
          "start": 4.2,
          "end": 8.5,
          "text": "exploring the hidden mountain waterfalls."
        }
      ]
    }
  },
  "created_at": "2026-09-01T14:30:00Z",
  "completed_at": "2026-09-01T14:30:25Z"
}
```

#### 3. Health Check
- **Route**: `GET /health`
- **Response (200 OK)**:
```json
{
  "status": "healthy",
  "database": "connected",
  "transcription_provider": "openai"
}
```

---

## 6. Webhook Payload Specifications

### 6.1 Stage Update Event
```json
{
  "event": "job.stage_updated",
  "job_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "status": "processing",
  "stage": "audio_converted",
  "timestamp": "2026-09-01T14:30:15Z"
}
```

### 6.2 Job Completed Event
```json
{
  "event": "job.completed",
  "job_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "status": "completed",
  "data": { ... },
  "timestamp": "2026-09-01T14:30:25Z"
}
```

### 6.3 Job Failed Event
```json
{
  "event": "job.failed",
  "job_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "status": "failed",
  "stage": "transcription",
  "error": "OpenAI API rate limit exceeded",
  "timestamp": "2026-09-01T14:30:20Z"
}
```

---

## 7. Database Entity Schema (Jobs Table)

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | VARCHAR(36) | Primary Key (UUIDv4) |
| `url` | TEXT | Target Instagram Reel/Post URL |
| `status` | VARCHAR(30) | `queued`, `processing`, `completed`, `failed` |
| `stage` | VARCHAR(50) | `initialized`, `metadata_extracted`, `audio_converted`, `transcribed`, `finished` |
| `metadata_json` | JSON / TEXT | Extracted post metadata & CDN URL |
| `video_path` | TEXT | Local temporary path for video file |
| `audio_path` | TEXT | Local temporary path for converted audio |
| `transcription_json` | JSON / TEXT | Extracted transcription data & segments |
| `error_message` | TEXT | Error details if failed |
| `transcription_provider` | VARCHAR(20) | `local` or `openai` |
| `webhook_url` | TEXT | Destination webhook URL |
| `webhook_status` | VARCHAR(30) | `pending`, `sent`, `failed` |
| `created_at` | TIMESTAMP | Creation timestamp |
| `updated_at` | TIMESTAMP | Last state update timestamp |
| `completed_at` | TIMESTAMP | Completion timestamp |

---

## 8. Environment Configuration Matrix

| Key | Default | Description |
| :--- | :--- | :--- |
| `API_KEY` | `insta_secret_key` | Master API Key for API endpoint access |
| `WEBHOOK_URL` | `""` | Global destination for job progress webhooks |
| `TRANSCRIPTION_PROVIDER` | `openai` | Switchable: `local` or `openai` |
| `OPENAI_API_KEY` | `""` | API Key for OpenAI Whisper |
| `LOCAL_WHISPER_MODEL` | `base` | Model size for local whisper (`tiny`, `base`, `small`, `medium`) |
| `DATABASE_URL` | `sqlite+aiosqlite:///./jobs.db` | Database connection string (SQLite or PostgreSQL) |
| `STORAGE_DIR` | `./storage` | Temporary media storage directory |
| `CLEANUP_TEMP_FILES` | `true` | Auto-delete temp MP4/WAV files after completion |
| `MAX_CONCURRENT_JOBS` | `3` | Concurrency limit for background worker pool |

