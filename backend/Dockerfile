# Multi-stage build for a production-ready JustResume AI Backend
FROM python:3.11-slim-bookworm

# Install LaTeX and system dependencies
# We use -slim but add the necessary texlive packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    texlive-latex-base \
    texlive-latex-recommended \
    texlive-latex-extra \
    texlive-fonts-recommended \
    texlive-plain-generic \
    unzip \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create output directory
RUN mkdir -p output

# Expose port
EXPOSE 8000

# Start the application
CMD ["python", "-m", "app.main"]
