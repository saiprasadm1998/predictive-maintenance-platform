"""api: REST routers, SSE stream and request dependencies (presentation layer).

Uses the public interfaces of every module. No module imports the api package.
"""

from pmp.api.app import create_app

__all__ = ["create_app"]
