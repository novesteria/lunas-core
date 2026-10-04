"""FastAPI app entrypoint. Single endpoint: GET /health."""

from datetime import datetime, timezone

from fastapi import FastAPI

from app import __version__

app = FastAPI(title="Health Service", version=__version__)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "version": __version__,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
