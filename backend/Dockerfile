FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LOG_LEVEL=WARNING \
    LATEX_OUTPUT_DIR=/app/output \
    TMPDIR=/app/tmp \
    HOME=/app/tmp \
    XDG_CACHE_HOME=/app/tmp/.cache \
    TEXMFVAR=/app/tmp/texmf-var \
    TEXMFCONFIG=/app/tmp/texmf-config

RUN mkdir -p /app/tmp /app/tmp/.cache /app/tmp/texmf-var /app/tmp/texmf-config

RUN apt-get -qq update \
    && apt-get -qq install -y --no-install-recommends -o=Dpkg::Use-Pty=0 \
    texlive-latex-base \
    texlive-latex-recommended \
    texlive-latex-extra \
    texlive-fonts-recommended \
    texlive-plain-generic \
    fonts-dejavu-core \
    curl \
    ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --quiet --progress-bar off --no-cache-dir --disable-pip-version-check --root-user-action=ignore -r requirements.txt

COPY . .
RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /app/output /app/tmp /app/tmp/.cache /app/tmp/texmf-var /app/tmp/texmf-config \
    && chown -R app:app /app/output /app/tmp \
    && chmod 755 /app/output /app/tmp

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/v1/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "warning", "--no-access-log"]
