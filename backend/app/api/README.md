# API Route File Naming Convention

This directory contains the FastAPI route handlers for VoxQuery.

## Naming Convention

- **`rest.py`**: Standard REST HTTP endpoints (e.g., `/health`, `/auth`, etc.).
- **`ws_*.py`**: WebSocket endpoints. They must be prefixed with `ws_` for easy identification.
  - Examples: `ws_audio.py`, `ws_video.py`, `ws_pipeline.py`.
- **`telemetry.py`**: Internal routes or webhooks related to telemetry, observabilty, etc.

By adhering to this convention, it is immediately obvious which transport mechanism a route file handles, keeping the module structure clean and strictly separated.
