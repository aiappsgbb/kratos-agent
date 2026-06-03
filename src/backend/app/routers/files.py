"""File download endpoint — serves files created by the agent on the container."""

import logging
import mimetypes
import os
import re

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# Directories the agent is allowed to write to and we are allowed to serve from.
_ALLOWED_ROOTS = ("/tmp",)

# MIME types allowed for inline (browser preview) serving.
# All other types are forced to attachment (download) to prevent reflected-content attacks.
_INLINE_ALLOWED_TYPES = frozenset(
    {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "image/svg+xml",
        "text/plain",
        "text/csv",
    }
)

# Filename validation: alphanumeric, hyphens, underscores, dots only
_SAFE_FILENAME_RE = re.compile(r"^[\w\-. ]+$")


def _is_safe_path(requested: str) -> bool:
    """Return True if the resolved path lives under an allowed root."""
    resolved = os.path.realpath(requested)
    return any(resolved.startswith(root + os.sep) or resolved == root for root in _ALLOWED_ROOTS)


@router.get("/download/{filename}")
async def download_file(
    filename: str,
    path: str = Query(..., description="Absolute path of the file on the server"),
    inline: bool = Query(False, description="Serve inline for browser preview instead of download"),
) -> FileResponse:
    """Serve a file the agent created so the user can download / preview it."""
    if not _SAFE_FILENAME_RE.match(filename):
        raise HTTPException(status_code=400, detail="Invalid filename")

    resolved = os.path.realpath(path)

    # Ensure the basename of the resolved path matches the requested filename
    if os.path.basename(resolved) != filename:
        raise HTTPException(status_code=400, detail="Filename mismatch")

    if not _is_safe_path(resolved):
        raise HTTPException(status_code=403, detail="Access denied")

    if not os.path.isfile(resolved):
        raise HTTPException(status_code=404, detail="File not found")

    media_type = mimetypes.guess_type(resolved)[0] or "application/octet-stream"
    safe_name = os.path.basename(resolved)

    # Only allow inline for safe MIME types; force download for everything else
    if inline and media_type not in _INLINE_ALLOWED_TYPES:
        inline = False

    disposition = "inline" if inline else "attachment"

    return FileResponse(
        path=resolved,
        media_type=media_type,
        filename=safe_name,
        headers={"Content-Disposition": f'{disposition}; filename="{safe_name}"'},
    )
