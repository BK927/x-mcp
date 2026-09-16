from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from .auth import browser_login, read_cookies, save_cookies
from .config import Settings
from .errors import XError
from .models import Query


def main() -> None:
    parser = argparse.ArgumentParser(prog="x-mcp", description="Read-only public X research MCP")
    commands = parser.add_subparsers(dest="command")
    serve = commands.add_parser("serve", help="Start MCP (default: stdio)")
    serve.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    auth = commands.add_parser("auth", help="Local owner-only session setup")
    auth_commands = auth.add_subparsers(dest="auth_command", required=True)
    auth_commands.add_parser("login", help="Open a dedicated browser for manual login")
    importer = auth_commands.add_parser("import", help="Import JSON or Netscape cookies")
    importer.add_argument("--file", type=Path, required=True)
    auth_commands.add_parser("status", help="Show presence/format, never cookie values")
    doctor = commands.add_parser("doctor", help="Sanitized configuration and provider health")
    doctor.add_argument(
        "--live", action="store_true", help="Opt in to public post/profile/search probes"
    )
    args = parser.parse_args()
    logging.basicConfig(
        stream=sys.stderr, level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s"
    )
    try:
        settings = Settings.from_env()
        if args.command == "auth":
            if args.auth_command == "login":
                asyncio.run(browser_login(settings.cookies_path))
                print("Session saved. Run x-mcp doctor to inspect configuration.")
            elif args.auth_command == "import":
                save_cookies(settings.cookies_path, read_cookies(args.file))
                print("Session imported. Cookie values were not printed.")
            else:
                read_cookies(settings.cookies_path)
                print(
                    "Session file is configured and well-formed; live access has not been tested."
                )
            return
        from .service import Service

        if args.command == "doctor":

            async def diagnose():
                service = Service(settings)
                try:
                    if args.live:
                        for query in [
                            Query(operation="post.post", target="20"),
                            Query(operation="user.profile", target="xdevelopers"),
                            Query(operation="search.posts", query="from:xdevelopers", limit=3),
                        ]:
                            try:
                                await service.query(query)
                            except (XError, TimeoutError):
                                pass
                    print(json.dumps(service.status("health"), ensure_ascii=False, indent=2))
                finally:
                    await service.close()

            asyncio.run(diagnose())
            return
        from .server import create_http_app, create_server

        if args.command == "serve":
            if args.host:
                settings.host = args.host
            if args.port:
                settings.port = args.port
        service = Service(settings)
        server = create_server(service)
        if args.command == "serve" and args.transport == "http":
            import uvicorn

            app = create_http_app(server, service)
            uvicorn.run(
                app, host=settings.host, port=settings.port, access_log=False, log_level="warning"
            )
        else:

            async def run_stdio():
                try:
                    await server.run_stdio_async()
                finally:
                    await service.close()

            asyncio.run(run_stdio())
    except XError as exc:
        print(json.dumps(exc.payload(), ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2) from None
    except (ValueError, OSError):
        print(
            "Invalid configuration or inaccessible local state. Check configuration values and paths.",
            file=sys.stderr,
        )
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
