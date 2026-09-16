"""No real X account or network: verify the pinned raw transport boundary."""

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from test_providers import gql_post

from x_mcp.auth import browser_login, save_cookies
from x_mcp.errors import XError
from x_mcp.models import Query
from x_mcp.providers.session import SessionProvider


async def test_raw_search_reads_one_page_closes_generator_and_preserves_cursor(tmp_path):
    calls = []

    async def search(query, *, limit, kv):
        calls.append((query, limit, kv))
        try:
            yield httpx.Response(200, json={"data": {"entries": [gql_post()]}})
            pytest.fail("Adapter must not request another upstream page eagerly")
        finally:
            calls.append("closed")

    api = SimpleNamespace(search_raw=search, _get_cursor=lambda body, kind: "next-page")
    provider = SessionProvider(tmp_path, tmp_path / "unused.json")
    page = await provider._fetch(
        api, Query(operation="search.posts", query="MCP", sort="top", limit=3), "first-page"
    )
    assert calls == [("MCP", 1, {"count": 3, "cursor": "first-page", "product": "Top"}), "closed"]
    assert page.next_cursor == "next-page"
    assert [p["id"] for p in page.items] == ["100"]


@pytest.mark.parametrize("public", [False, True])
async def test_list_results_require_public_proof(tmp_path, public):
    async def pages(*args, **kwargs):
        yield httpx.Response(
            200,
            json={
                "data": {
                    "list": {"mode": "Public" if public else "Private"},
                    "entries": [gql_post()],
                }
            },
        )

    api = SimpleNamespace(list_timeline_raw=pages, _get_cursor=lambda body, kind: None)
    provider = SessionProvider(tmp_path, tmp_path / "unused.json")
    if public:
        page = await provider._fetch(api, Query(operation="list.posts", target="123"), None)
        assert len(page.items) == 1
    else:
        with pytest.raises(XError, match="visibility") as error:
            await provider._fetch(api, Query(operation="list.posts", target="123"), None)
        assert error.value.code == "PUBLIC_UNVERIFIED"


async def test_unknown_community_is_rejected_before_timeline_query(tmp_path):
    timeline = AsyncMock()
    api = SimpleNamespace(
        community_info_raw=AsyncMock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "communityResults": {"result": {"join_policy": "Open", "name": "Unknown"}}
                    }
                },
            )
        ),
        community_tweets_raw=timeline,
    )
    provider = SessionProvider(tmp_path, tmp_path / "unused.json")
    with pytest.raises(XError) as error:
        await provider._fetch(api, Query(operation="community.posts", target="123"), None)
    assert error.value.code == "PUBLIC_UNVERIFIED"
    timeline.assert_not_called()


async def test_single_owner_expiry_survives_restart_and_telemetry_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("TWS_TELEMETRY", "1")
    directory = tmp_path / "state"
    path = directory / "session.json"
    cookies = {"auth_token": "synthetic-auth", "ct0": "synthetic-csrf"}
    save_cookies(path, cookies)
    provider = SessionProvider(directory, path)
    api = await provider._client()
    assert os.environ["TWS_TELEMETRY"] == "0"
    assert [a.username for a in await api.pool.get_all()] == ["owner"]
    await api.pool.set_active("owner", False)
    await provider.close()
    api = await provider._client()
    assert not (await api.pool.get("owner")).active
    with pytest.raises(XError) as error:
        await provider._unavailable()
    assert error.value.code == "SESSION_EXPIRED"
    save_cookies(path, {**cookies, "auth_token": "synthetic-new-auth"})
    api = await provider._client()
    assert (await api.pool.get("owner")).active
    await api.pool.add_account_cookies("unexpected", '{"auth_token":"fake","ct0":"fake"}')
    await provider.close()
    with pytest.raises(XError) as error:
        await provider._client()
    assert error.value.code == "INVALID_SESSION"


async def test_manual_browser_login_saves_only_x_cookies_and_always_closes(tmp_path, monkeypatch):
    page = SimpleNamespace(goto=AsyncMock())
    context = SimpleNamespace(
        new_page=AsyncMock(return_value=page),
        cookies=AsyncMock(
            return_value=[
                {"domain": ".x.com", "name": "auth_token", "value": "synthetic-auth"},
                {"domain": ".x.com", "name": "ct0", "value": "synthetic-csrf"},
                {"domain": ".x.com", "name": "unneeded", "value": "discard"},
            ]
        ),
    )
    browser = SimpleNamespace(new_context=AsyncMock(return_value=context), close=AsyncMock())
    launch = AsyncMock(return_value=browser)

    class PlaywrightContext:
        async def __aenter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(launch=launch))

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr("playwright.async_api.async_playwright", PlaywrightContext)
    monkeypatch.setattr("builtins.input", lambda _: "")
    path = tmp_path / "state" / "session.json"
    await browser_login(path)
    launch.assert_awaited_once_with(headless=False)
    browser.close.assert_awaited_once()
    assert "discard" not in path.read_text()
    context.cookies.return_value = []
    with pytest.raises(XError):
        await browser_login(path)
    assert browser.close.await_count == 2
