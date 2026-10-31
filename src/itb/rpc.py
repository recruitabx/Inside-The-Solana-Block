"""Small JSON-RPC client.

Design points:
* The endpoint URL usually embeds an API key, so it is never printed: repr() and every
  error message only show the host name.
* Supports JSON-RPC batches (several calls in ONE HTTP request). The experiment uses this
  to hand all transactions of one probe to the provider at the same instant.
* A token-bucket limiter keeps us inside the provider's rate limit.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class RpcError(Exception):
    """JSON-RPC level error (the server answered with an "error" object)."""

    def __init__(self, method: str, error: dict[str, Any]):
        self.method = method
        self.code = error.get("code")
        self.error = error
        super().__init__(f"{method}: rpc error {self.code}: {str(error.get('message'))[:200]}")


class TransportError(Exception):
    """HTTP or network failure. Message never contains the URL."""


def host_of(url: str) -> str:
    return urllib.parse.urlparse(url).hostname or "?"


class TokenBucket:
    def __init__(self, rate_per_s: float, burst: float):
        self.rate, self.capacity = rate_per_s, burst
        self.tokens, self.t = burst, time.monotonic()
        self.lock = threading.Lock()

    def take(self, n: float = 1.0) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.t) * self.rate)
                self.t = now
                if self.tokens >= n:
                    self.tokens -= n
                    return
                wait = (n - self.tokens) / self.rate
            time.sleep(wait)


class Rpc:
    def __init__(self, url: str | None = None, *, env: str = "RPC_URL", timeout: float = 30.0,
                 rate_per_s: float = 8.0, burst: float = 8.0, retries: int = 6):
        url = url or os.environ.get(env)
        if not url:
            raise SystemExit(f"environment variable {env} is not set (see .env.example)")
        self._url = url
        self.host = host_of(url)
        self.timeout = timeout
        self.retries = retries
        self.bucket = TokenBucket(rate_per_s, burst)
        self._id = 0

    def __repr__(self) -> str:  # never leak the key
        return f"Rpc(host={self.host!r})"

    def _post(self, payload: Any, cost: float) -> Any:
        body = json.dumps(payload).encode()
        delay = 0.5
        for attempt in range(self.retries + 1):
            self.bucket.take(cost)
            req = urllib.request.Request(self._url, data=body, headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                status = e.code
                if status in (408, 413, 425, 429, 500, 502, 503, 504) and attempt < self.retries:
                    time.sleep(delay); delay *= 2
                    continue
                raise TransportError(f"HTTP {status} from {self.host}") from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt < self.retries:
                    time.sleep(delay); delay *= 2
                    continue
                raise TransportError(f"network error talking to {self.host}: {type(e).__name__}") from None
        raise TransportError(f"retries exhausted for {self.host}")

    def call(self, method: str, params: list | None = None) -> Any:
        self._id += 1
        d = self._post({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or []}, 1.0)
        if "error" in d:
            raise RpcError(method, d["error"])
        return d["result"]

    def batch(self, calls: list[tuple[str, list]], *, retry: bool = True) -> list[dict]:
        """Send several calls in ONE HTTP request. Returns raw per-call responses in call order.

        retry=False is used for send batches: re-posting a send batch would
        change the arrival timing we are trying to control, so a failed send is recorded as
        failed rather than silently retried.
        """
        base = self._id
        payload = [{"jsonrpc": "2.0", "id": base + i + 1, "method": m, "params": p} for i, (m, p) in enumerate(calls)]
        self._id += len(calls)
        saved = self.retries
        if not retry:
            self.retries = 0
        try:
            resp = self._post(payload, float(len(calls)))
        finally:
            self.retries = saved
        if not isinstance(resp, list):
            raise TransportError(f"batch rejected by {self.host}: {str(resp)[:200]}")
        by_id = {r.get("id"): r for r in resp}
        return [by_id.get(base + i + 1, {"error": {"code": None, "message": "missing in batch reply"}}) for i in range(len(calls))]
