FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install curl, ffmpeg, certificates, and libraries for OpenCV / PaddleOCR
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    ca-certificates \
    libgomp1 \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install PaddlePaddle CPU and PaddleOCR
RUN pip install --no-cache-dir paddlepaddle==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/ \
    && pip install --no-cache-dir "paddleocr[all]"

# Install Playwright Chromium and required OS dependencies
RUN playwright install --with-deps chromium

# Copy application code
COPY app/ ./app/

# Create storage directories
RUN mkdir -p /app/storage/video /app/storage/audio /app/storage/images

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
