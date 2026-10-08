# syntax=docker/dockerfile:1

FROM python:3.11-slim AS builder

WORKDIR /build
ENV PYTHONDONTWRITEBYTECODE=1
# constraints.txt pins the exact versions the project was tested with
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt -c constraints.txt


FROM python:3.11-slim AS runtime

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8

COPY --from=builder /install /usr/local
COPY . .

# Run as an unprivileged user; the only writable location is the validation report directory.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /app/validation_reports \
    && chown -R app:app /app/validation_reports
USER app

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
