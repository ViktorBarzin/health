"""Simple in-memory rate limiter for auth endpoints."""

import time
from collections import defaultdict

from fastapi import HTTPException, Request, status


# Store: IP -> list of request timestamps
_request_log: dict[str, list[float]] = defaultdict(list)

_MAX_REQUESTS = 10
_WINDOW_SECONDS = 60


async def check_rate_limit(request: Request) -> None:
    """FastAPI dependency that enforces per-IP rate limiting.

    Raises HTTP 429 if the client exceeds the request threshold.
    """
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    window_start = now - _WINDOW_SECONDS

    # Prune old entries
    timestamps = _request_log[client_ip]
    _request_log[client_ip] = [t for t in timestamps if t > window_start]

    if len(_request_log[client_ip]) >= _MAX_REQUESTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please try again later.",
        )

    _request_log[client_ip].append(now)
