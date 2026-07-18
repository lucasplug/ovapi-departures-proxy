"""Entrypoint: `python -m app` starts uvicorn bound on 0.0.0.0.

Binding to 0.0.0.0 is required so the service is reachable from other hosts
(e.g. the Home Assistant VM); 127.0.0.1 would only work inside the container.
"""

import logging
import os

import uvicorn

from .config import load_port

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=load_port(),
        log_config=None,
    )
