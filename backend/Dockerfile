FROM python:3.11-slim
WORKDIR /app

# Install system dependencies: tesseract OCR + Chinese fonts for PDF generation
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    fonts-wqy-microhei \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple/ \
    && pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple/ --trusted-host pypi.tuna.tsinghua.edu.cn
COPY app ./app
RUN mkdir -p /app/storage/uploads /app/storage/reports /app/storage/templates /app/storage/contracts /app/storage/BI_Data
ENV STORAGE_DIR=/app/storage
ENV DATABASE_PATH=/app/storage/audit_platform.db
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--limit-concurrency", "50"]
