"""Serve the built public SPA on the same origin, without exposing private API routes."""

from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope


class PublicStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        if path in (".", "analyze", "examples"):
            return await super().get_response("index.html", scope)
        # No admin SPA or API fallback on this isolated public host.
        if path.startswith(("admin", "api/")):
            raise HTTPException(404)
        return await super().get_response(path, scope)
