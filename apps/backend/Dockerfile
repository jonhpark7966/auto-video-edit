FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml .
COPY src/ src/

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Create directories for uploads/outputs
RUN mkdir -p /app/uploads /app/outputs /app/temp

# Expose port
EXPOSE 8000

# Run the application
CMD ["python", "-m", "avid.main"]
