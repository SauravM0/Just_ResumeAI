# Production backend image for Render/Railway — Docker context is the repo root.
FROM python:3.11-slim-bookworm

# Prevent Python from buffering stdout/stderr and writing .pyc files
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive

# Install LaTeX and system dependencies for PDF compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Core LaTeX for pdflatex
    texlive-latex-base \
    texlive-latex-recommended \
    texlive-latex-extra \
    texlive-fonts-recommended \
    texlive-plain-generic \
    # xelatex support for CJK / advanced font handling
    texlive-xetex \
    # Fonts
    fonts-dejavu-core \
    fonts-noto-cjk \
    # Utilities
    curl \
    ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Verify pdflatex is available
RUN which pdflatex && pdflatex --version | head -1

WORKDIR /app

# Install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/ .

# Create output directory for generated PDFs and session data
RUN mkdir -p /app/output && chmod 755 /app/output

EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

CMD ["python", "-m", "app.main"]
