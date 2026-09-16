import pytest
from conftest import FakeProvider, make_post

from x_mcp.errors import XError
from x_mcp.models import ProviderPage, Query


async def test_fallback_only_on_first_transient_failure(service_factory):
    fx = FakeProvider("fxtwitter", {None: XError("PROVIDER_UNAVAILABLE", "down", retryable=True)})
    session = FakeProvider(
        "twscrape",
        {
            None: ProviderPage("twscrape", items=[make_post()], next_cursor="next"),
            "next": XError("PROVIDER_UNAVAILABLE", "down", retryable=True),
        },
    )
    service = service_factory(fx=fx, session=session)
    query = Query(operation="user.posts", target="example")
    initial = await service.query(query)
    assert initial["meta"]["provider"] == "twscrape"
    assert len(fx.calls) == 1
    with pytest.raises(XError):
        await service.query(query, cursor=initial["page"]["next_cursor"])
    assert len(fx.calls) == 1


@pytest.mark.parametrize(
    "page",
    [
        ProviderPage("fxtwitter", items=[]),
        XError("NOT_FOUND", "missing"),
        XError("RATE_LIMITED", "wait", retryable=True),
    ],
)
async def test_no_fallback_for_empty_not_found_or_rate_limit(service_factory, page):
    fx, session = FakeProvider("fxtwitter", {None: page}), FakeProvider("twscrape")
    service = service_factory(fx=fx, session=session)
    try:
        response = await service.query(Query(operation="user.posts", target="example"))
        assert response["items"] == []
    except XError:
        pass
    assert not session.calls


async def test_session_first_search_cache_and_offline_analysis(service_factory):
    posts = [
        make_post(1, "#MCP #개발 https://example.com/a"),
        make_post(2, "#MCP", metrics={"likes": None}),
    ]
    session = FakeProvider(
        "twscrape", {None: ProviderPage("twscrape", items=posts, next_cursor="next")}
    )
    fx = FakeProvider("fxtwitter")
    service = service_factory(fx=fx, session=session)
    query = Query(operation="search.posts", query="MCP")
    first = await service.query(query)
    await service.query(query)
    result = service.analyze([first["result_id"], first["result_id"]])
    data = result["data"]
    assert data["sample_size"] == 2
    assert data["source_has_more"]
    assert data["engagement"]["likes"] == {"sum": 2, "known_posts": 1, "missing_posts": 1}
    assert data["engagement"]["views"]["sum"] is None
    assert {item["tag"] for item in data["hashtags"]} == {"mcp", "개발"}
    assert data["link_domains"] == [{"domain": "example.com", "occurrences": 1}]
    assert len(session.calls) == 1 and not fx.calls


def test_capability_state_is_not_a_live_success_claim(service_factory):
    service = service_factory()
    caps = service.status()["data"]["capabilities"]
    assert caps["search.posts"]["fxtwitter"] == {"state": "available", "validation": "not_verified"}
    assert caps["search.posts"]["twscrape"]["state"] == "requires_session"


async def test_session_analysis_and_health_are_bound_to_original_session(service_factory):
    session = FakeProvider("twscrape", {None: ProviderPage("twscrape", items=[make_post()])})
    service = service_factory(session=session)
    saved = await service.query(Query(operation="search.posts", query="test"))
    analysis = service.analyze([saved["result_id"]])
    assert service.status()["data"]["session"] == "live_verified_at_recorded_time"
    session.identity = "new-session"
    assert service.status()["data"]["session"] == "configured_not_live_verified"
    assert not service.status("health")["data"]["observations"]
    with pytest.raises(XError) as error:
        service.result_get(analysis["result_id"])
    assert error.value.code == "SESSION_CHANGED"
