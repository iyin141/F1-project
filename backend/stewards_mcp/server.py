"""Entry point of the F1 Control Room MCP server (stdio).

    cd backend && python stewards_mcp/server.py

The folder is `stewards_mcp`, not `mcp`, so it can never shadow the MCP SDK. The server itself is `api/assistant/mcp_server.py`.
stdout belongs to the protocol; logging goes to stderr.
"""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path = [p for p in sys.path if Path(p or ".").resolve() != Path(__file__).resolve().parent]  # never import this folder as `mcp`
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "f1_project.settings")

import django  # noqa: E402

django.setup()

from api.assistant.mcp_server import build_server  # noqa: E402

if __name__ == "__main__":
    build_server().run("stdio")
