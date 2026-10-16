"""Rate-limit mobile auth requests by user when possible, otherwise by IP."""

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from server.auth.security import TokenError, decode_access_token


def _identify(request: Request) -> str:
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        try:
            return f"user:{decode_access_token(authorization[7:])}"
        except (TokenError, RuntimeError, ValueError):
            pass
    return f"ip:{get_remote_address(request)}"


limiter = Limiter(key_func=_identify)