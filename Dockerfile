FROM python:3.12-slim

LABEL org.opencontainers.image.title="Clinical Question-Evidence Studio"
LABEL org.opencontainers.image.description="Educational clinical informatics portfolio prototype"
LABEL org.opencontainers.image.version="0.1.0"

WORKDIR /app

# System dependencies (needed for some Python packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies before copying source (improves layer caching)
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir -e ".[dev]"

# Copy application source
COPY . .

# Create non-root user for security
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Expose ports
EXPOSE 8000 8501

# Default command: run Streamlit app
# Override with docker compose for the API service
CMD ["streamlit", "run", "app/Home.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
