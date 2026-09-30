FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv export --no-dev --format requirements-txt --output-file requirements.txt \
    && pip install --no-cache-dir -r requirements.txt \
    && rm requirements.txt

COPY ./src/ ./src/
# The MCP server answers `list_checker_types` / `describe_checker_type` from these files.
COPY ./openspec/ ./openspec/

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
