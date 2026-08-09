"""Outbound proxy helpers (Webshare / generic HTTP proxies)."""

from __future__ import annotations

import hashlib
import random
from urllib.parse import urlparse


def parse_proxy_list(*raw_values: str) -> list[str]:
    """Split comma/newline proxy URLs; ignore blanks."""
    out: list[str] = []
    for raw in raw_values:
        if not raw or not str(raw).strip():
            continue
        for part in str(raw).replace("\n", ",").split(","):
            p = part.strip()
            if p:
                out.append(p)
    return out


def choose_proxy(proxies: list[str], *, sticky: str | None = None) -> str | None:
    """Pick one proxy. Sticky key → stable assignment; else random."""
    if not proxies:
        return None
    if sticky is None:
        return random.choice(proxies)
    digest = hashlib.sha256(sticky.encode()).hexdigest()
    return proxies[int(digest[:8], 16) % len(proxies)]


def proxy_log_label(url: str) -> str:
    """Host:port only — never log credentials."""
    parsed = urlparse(url)
    host = parsed.hostname or "?"
    if parsed.port:
        return f"{host}:{parsed.port}"
    return host
