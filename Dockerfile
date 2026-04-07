FROM python:3.11-slim

# Install FFmpeg and other dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app
COPY . .

# Ensure static/downloads exists
RUN mkdir -p static/downloads

# Expose port and run the app
EXPOSE 7860
CMD ["gunicorn", "-b", "0.0.0.0:7860", "--timeout", "120", "--workers", "2", "app:app"]
