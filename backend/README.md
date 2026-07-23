# Backend

FastAPI + LangGraph service for the AI Personal Assistant. See the [project root README](../README.md) for architecture, setup, and everything else — this file is just package metadata for `uv`.

Quick start:

```bash
uv sync
cp .env.example .env
uv run uvicorn app.main:app --reload --port 8000
```
