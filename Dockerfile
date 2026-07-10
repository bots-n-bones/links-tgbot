FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY . .
RUN pip install --no-cache-dir -e .[dev]

# Editable install's meta-path finder does not reliably register in every
# invocation mode (console-script entry points like uvicorn don't prepend
# cwd to sys.path) — set PYTHONPATH explicitly so imports work regardless
# of how each service's process is started.
ENV PYTHONPATH=/app

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
