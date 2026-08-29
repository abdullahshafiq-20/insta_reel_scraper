# Instagram Reel Scraper FastAPI Service

A high-performance **FastAPI** service that extracts Instagram Reel metadata (creator, caption, stats, hashtags, mentions) and direct playable progressive MP4 video CDN URLs in **pure JSON** without saving any files to disk.

---

## Features

- **Direct In-Memory JSON Response**: No video files or temporary JSON files are written to disk.
- **Progressive MP4 URL Resolution**: Returns full progressive video stream URLs ready for streaming or downloading on demand.
- **API Key Security**: Access control via `X-API-Key` HTTP header or `?api_key=` URL parameter.
- **Both GET and POST Support**: Use either JSON request payloads or simple GET query params.
- **Interactive Swagger UI**: Full OpenAPI docs and live interactive testing at `/docs`.

---

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env` (or customize the existing `.env`):
```ini
API_KEY=my_instagram_scraper_secret_key_123
HOST=0.0.0.0
PORT=8000
TIMEOUT_MS=30000
HEADLESS=true
```

### 3. Run the FastAPI Server
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
or run directly with Python:
```bash
python main.py
```

The API will start at: `http://localhost:8000`
Interactive documentation (Swagger UI): `http://localhost:8000/docs`

---

## API Usage Examples

### 1. POST Request (`/api/v1/reel`)

**Using `curl` with `X-API-Key` header:**
```bash
curl -X POST "http://localhost:8000/api/v1/reel" \
     -H "Content-Type: application/json" \
     -H "X-API-Key: my_instagram_scraper_secret_key_123" \
     -d '{
       "url": "https://www.instagram.com/reel/DE48s0_vG4v/"
     }'
```

**Using Python `requests`:**
```python
import requests

url = "http://localhost:8000/api/v1/reel"
headers = {
    "X-API-Key": "my_instagram_scraper_secret_key_123",
    "Content-Type": "application/json"
}
payload = {
    "url": "https://www.instagram.com/reel/DE48s0_vG4v/"
}

response = requests.post(url, json=payload, headers=headers)
data = response.json()
print(data)
```

---

### 2. GET Request (`/api/v1/reel`)

**Using query parameter in browser or curl:**
```bash
curl "http://localhost:8000/api/v1/reel?url=https://www.instagram.com/reel/DE48s0_vG4v/&api_key=my_instagram_scraper_secret_key_123"
```

---

## Example Response

```json
{
  "success": true,
  "data": {
    "shortcode": "DE48s0_vG4v",
    "url": "https://www.instagram.com/reel/DE48s0_vG4v/",
    "username": "example_creator",
    "caption": "Amazing sunset reel #nature #explore",
    "hashtags": [
      "nature",
      "explore"
    ],
    "mentions": [],
    "like_count_raw": "14.2K",
    "comment_count_raw": "210",
    "share_count_raw": "1.1K",
    "video_url": "https://instagram.fdel...mp4?_nc_cat=101&...",
    "video_urls_candidates": [
      "https://instagram.fdel...mp4?_nc_cat=101&..."
    ],
    "source": "headless_browser_dom"
  }
}
```

---

## Project Structure

```
insta_reel_scraper/
├── .env                  # Live environment configuration
├── .env.example          # Template environment configuration
├── config.py             # App configuration & environment settings
├── models.py             # Pydantic request and response schemas
├── security.py           # API Key authentication dependency
├── scraper.py            # Async Playwright in-memory scraper
├── main.py               # FastAPI application and routing
├── v1.py                 # Original CLI script for local file downloads
├── requirements.txt      # Dependency list
└── README.md             # Documentation
```

