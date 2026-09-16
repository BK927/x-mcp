from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from .errors import XError
from .models import dumps

COOKIE_NAMES = {"auth_token", "ct0"}
COOKIE_DOMAINS = {"x.com", ".x.com", "twitter.com", ".twitter.com"}


def protect(path: Path, *, directory: bool = False) -> None:
    """Only protect paths owned/created by this application, never arbitrary parents."""
    if os.name == "nt":
        import ctypes
        import ctypes.wintypes

        # Resolve the current identity through Windows, avoiding shell interpolation.
        size = ctypes.wintypes.ULONG(256)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not ctypes.windll.secur32.GetUserNameExW(2, buffer, ctypes.byref(size)):
            raise XError(
                "STATE_PERMISSIONS", "Unable to identify the Windows account for private storage."
            )
        rights = "(OI)(CI)F" if directory else "F"
        result = subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{buffer.value}:{rights}"],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=False,
        )
        if result.returncode:
            raise XError("STATE_PERMISSIONS", "Unable to restrict private storage permissions.")
    else:
        path.chmod(0o700 if directory else 0o600)


def ensure_private_directory(path: Path) -> None:
    resolved = path.resolve()
    if resolved in {Path.home().resolve(), Path.cwd().resolve(), Path(resolved.anchor)}:
        raise XError(
            "STATE_PERMISSIONS",
            "Use a dedicated subdirectory for X MCP state, not a home, project, or filesystem root.",
        )
    if path.is_symlink():
        raise XError("STATE_PERMISSIONS", "Private storage must not be a symbolic link.")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    protect(path, directory=True)


def parse_cookies(text: str) -> dict[str, str]:
    if len(text.encode()) > 2 * 1024 * 1024:
        raise XError("INVALID_SESSION", "Cookie input is too large.")
    try:
        value: Any = json.loads(text)
    except json.JSONDecodeError:
        value = []
        for line in text.splitlines():
            if line.startswith("#HttpOnly_"):
                line = line[len("#HttpOnly_") :]
            elif not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) == 7:
                value.append(
                    {"domain": parts[0], "expires": parts[4], "name": parts[5], "value": parts[6]}
                )
    if isinstance(value, dict) and isinstance(value.get("cookies"), list):
        value = value["cookies"]
    result = {}
    if isinstance(value, dict):
        result = {name: value.get(name) for name in COOKIE_NAMES}
    elif isinstance(value, list):
        for item in value:
            if (
                not isinstance(item, dict)
                or item.get("domain") not in COOKIE_DOMAINS
                or item.get("name") not in COOKIE_NAMES
            ):
                continue
            expiry = item.get("expires", item.get("expirationDate", 0))
            try:
                if 0 < float(expiry or 0) <= time.time():
                    continue
            except (ValueError, TypeError):
                continue
            name, token = item["name"], item.get("value")
            if name in result and result[name] != token:
                raise XError(
                    "INVALID_SESSION",
                    "Cookie file contains conflicting X sessions; export one account only.",
                )
            result[name] = token
    if any(
        not isinstance(result.get(name), str)
        or not 1 <= len(result[name]) <= 8192
        or any(c in result[name] for c in "\r\n;\x00")
        for name in COOKIE_NAMES
    ):
        raise XError("INVALID_SESSION", "Both auth_token and ct0 from one X session are required.")
    return result


def read_cookies(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise XError(
            "AUTH_REQUIRED",
            "Run x-mcp auth login or x-mcp auth import --file PATH on the server owner account.",
        )
    if path.is_symlink():
        raise XError("INVALID_SESSION", "Session files must not be symbolic links.")
    try:
        return parse_cookies(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError) as exc:
        raise XError("INVALID_SESSION", "Session file could not be read.") from exc


def fingerprint(cookies: dict[str, str]) -> str:
    return hashlib.sha256(dumps(sorted(cookies.items())).encode()).hexdigest()


def save_cookies(path: Path, cookies: dict[str, str]) -> None:
    cookies = parse_cookies(dumps(cookies))
    ensure_private_directory(path.parent)
    fd, tmp = tempfile.mkstemp(prefix=".session-", dir=path.parent)
    temp = Path(tmp)
    try:
        os.close(fd)
        protect(temp)
        temp.write_text(dumps(cookies), encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


async def browser_login(path: Path) -> None:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise XError(
            "BROWSER_NOT_INSTALLED",
            "Install the browser extra and run playwright install chromium.",
        ) from exc
    # A fresh isolated context; existing browser profiles/passwords are never imported.
    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch(headless=False)
        except Exception as exc:
            raise XError(
                "BROWSER_UNAVAILABLE",
                "Chromium could not start. Run playwright install chromium, or import a cookie file.",
            ) from exc
        try:
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto("https://x.com/i/flow/login", wait_until="domcontentloaded")
            await asyncio.to_thread(
                input, "Complete X login in the dedicated window, then press Enter here: "
            )
            cookies = parse_cookies(dumps(await context.cookies(["https://x.com"])))
            save_cookies(path, cookies)
        finally:
            await browser.close()
