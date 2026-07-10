FROM python:3.11-slim

WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install dependencies and a production server (gunicorn)
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy application code
COPY . .

# Mở port 5000 cho Flask
EXPOSE 5000

# Chạy ứng dụng qua gunicorn thay vì dev server
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]
