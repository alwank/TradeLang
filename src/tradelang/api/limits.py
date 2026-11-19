"""Local editor transport limits. Body caps apply even without Content-Length."""

import ipaddress
import json
import math
import time
from collections import deque
from uuid import uuid4

from starlette.datastructures import Headers
from starlette.responses import JSONResponse

MAX_BODY = 128 * 1024
ORIGIN = "http://127.0.0.1:3000"
HOST = "127.0.0.1:8000"


def reject_non_json_number(value: str):
    raise ValueError(f"{value} is outside the JSON number syntax")


def failure(status, code, message, headers=None, *, diagnostics=None):
    return JSONResponse(
        dict(
            schema_version=1,
            request_id=str(uuid4()),
            error=dict(
                code=code,
                message=message,
                diagnostics=[] if diagnostics is None else diagnostics,
                retryable=status in (429, 503),
            ),
        ),
        status_code=status,
        headers=headers,
    )


class EditorLimits:
    def __init__(self, app):
        self.app = app
        self.history: dict[str, deque[float]] = {}
        self.active = 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        peer = scope.get("client")
        try:
            local = peer and ipaddress.ip_address(peer[0]).is_loopback
        except ValueError:
            local = False
        if not local or headers.getlist("host") != [HOST]:
            return await failure(
                403, "E_LOCAL_ONLY", "Loopback client and configured Host required"
            )(scope, receive, send)
        method = scope["method"]
        if method not in {"POST", "PUT", "DELETE"}:
            return await self.app(scope, receive, send)
        if headers.getlist("origin") != [ORIGIN]:
            return await failure(403, "E_ORIGIN", "Unrecognized request origin")(
                scope, receive, send
            )
        path = scope["path"]
        if method == "DELETE" or path == "/api/v1/datasets/import":
            return await self.app(scope, receive, send)
        if (
            headers.get("content-type", "").partition(";")[0].strip().lower()
            != "application/json"
        ):
            return await failure(415, "E_CONTENT_TYPE", "Expected application/json")(
                scope, receive, send
            )
        editor = path in {"/api/v1/strategies/validate", "/api/v1/strategies/explain"}
        if editor:
            now = time.monotonic()
            for key, history in list(self.history.items()):
                while history and now - history[0] >= 60:
                    history.popleft()
                if not history:
                    del self.history[key]
            history = self.history.setdefault(peer[0], deque())
            if len(history) >= 30 or self.active >= 4:
                retry = (
                    max(1, math.ceil(60 - (now - history[0])))
                    if len(history) >= 30
                    else 1
                )
                return await failure(
                    429,
                    "E_RATE_LIMIT",
                    "Local editor request limit reached",
                    {"Retry-After": str(retry)},
                )(scope, receive, send)
            history.append(now)
            self.active += 1
        try:
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                if len(body) + len(chunk) > MAX_BODY:
                    return await failure(
                        413, "E_REQUEST_SIZE", "JSON body exceeds 128 KiB"
                    )(scope, receive, send)
                body.extend(chunk)
                if not message.get("more_body", False):
                    break
            # The framework's decoder also accepts UTF-16 and NaN.
            # Check the bounded wire body against our UTF-8 JSON contract.
            try:
                json.loads(body.decode("utf-8"), parse_constant=reject_non_json_number)
            except (ValueError, RecursionError):
                return await failure(400, "E_JSON", "Malformed UTF-8 JSON")(
                    scope, receive, send
                )
            replayed = False

            async def replay():
                nonlocal replayed
                if replayed:
                    return await receive()
                replayed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}

            return await self.app(scope, replay, send)
        finally:
            if editor:
                self.active -= 1
