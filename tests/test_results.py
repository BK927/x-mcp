import json
import time

import pytest
from conftest import FakeProvider, make_post

from x_mcp.errors import XError
from x_mcp.models import ProviderPage, Query, dumps
from x_mcp.store import Store


async def test_provider_overfetch_survives_budget_paging_and_restart(tmp_path):
    from x_mcp.config import Settings
    from x_mcp.service import Service

    pages = {
        None: ProviderPage(
            "fxtwitter", items=[make_post(n) for n in range(20)], next_cursor="page-two"
        ),
        "page-two": ProviderPage("fxtwitter", items=[make_post(n) for n in range(18, 25)]),
    }
    fx = FakeProvider("fxtwitter", pages)
    settings = Settings(state_dir=tmp_path / "state")
    service = Service(settings, fx=fx, session=FakeProvider("twscrape", configured=False))
    query = Query(operation="user.posts", target="example", limit=3)
    response = await service.query(query)
    ids = [x["id"] for x in response["items"]]
    cursor = response["page"]["next_cursor"]
    await service.close()
    service = Service(settings, fx=fx, session=FakeProvider("twscrape", configured=False))
    while cursor:
        response = await service.query(query, cursor=cursor)
        ids.extend(x["id"] for x in response["items"])
        cursor = response["page"]["next_cursor"]
        assert len(fx.calls) <= 2
    assert ids == [str(n) for n in range(25)]
    assert len(fx.calls) == 2
    await service.close()


async def test_long_unicode_text_is_losslessly_recoverable(service_factory):
    original = "한글😀日本語\n" * 5000
    fx = FakeProvider("fxtwitter", {None: ProviderPage("fxtwitter", data=make_post(text=original))})
    service = service_factory(fx=fx, max_bytes=4096)
    response = await service.query(Query(operation="post.post", target="100"), detail="full")
    assert len(dumps(response).encode()) <= 4096
    assert response["data"]["fields_truncated"]
    parts, cursor = [], None
    while True:
        piece = service.result_get(response["result_id"], item_id="100", cursor=cursor)
        assert len(dumps(piece).encode()) <= 4096
        parts.append(piece["data"]["text"])
        cursor = piece["page"]["next_cursor"]
        if not cursor:
            break
    assert "".join(parts) == original
    assert len(fx.calls) == 1


async def test_full_json_chunks_reconstruct_nested_fields(service_factory):
    item = make_post(media=[{"alt_text": "画像" * 4000}])
    service = service_factory(
        fx=FakeProvider("fxtwitter", {None: ProviderPage("fxtwitter", data=item)}), max_bytes=4096
    )
    initial = await service.query(Query(operation="post.post", target="100"))
    parts, cursor = [], None
    while True:
        piece = service.result_get(initial["result_id"], item_id="100", field="json", cursor=cursor)
        parts.append(piece["data"]["text"])
        cursor = piece["page"]["next_cursor"]
        if not cursor:
            break
    assert json.loads("".join(parts)) == item


async def test_page_budget_does_not_drop_items(service_factory):
    items = [make_post(n, "한" * 600) for n in range(50)]
    service = service_factory(
        fx=FakeProvider("fxtwitter", {None: ProviderPage("fxtwitter", items=items)}), max_bytes=4096
    )
    query = Query(operation="search.posts", query="test", limit=50)
    response = await service.query(query)
    ids = []
    while True:
        assert service.store.size(response) <= 4096
        ids.extend(item["id"] for item in response["items"])
        if not response["page"]["next_cursor"]:
            break
        response = await service.query(query, cursor=response["page"]["next_cursor"])
    assert ids == [str(n) for n in range(50)]


async def test_local_result_read_never_fetches_next_source_page(service_factory):
    fx = FakeProvider(
        "fxtwitter", {None: ProviderPage("fxtwitter", items=[make_post()], next_cursor="remote")}
    )
    service = service_factory(fx=fx)
    initial = await service.query(Query(operation="search.posts", query="test"))
    saved = service.result_get(initial["result_id"])
    assert saved["page"]["next_cursor"] is None
    assert saved["page"]["source_cursor"]
    assert len(fx.calls) == 1


async def test_modified_mismatched_expired_and_session_bound_cursors(service_factory):
    session = FakeProvider(
        "twscrape", {None: ProviderPage("twscrape", items=[make_post(1), make_post(2)])}
    )
    service = service_factory(session=session)
    query = Query(operation="search.posts", query="first", limit=1)
    initial = await service.query(query)
    cursor = initial["page"]["next_cursor"]
    with pytest.raises(XError, match="modified"):
        service.store.decode(cursor + "x")
    with pytest.raises(XError) as wrong:
        await service.query(Query(operation="search.posts", query="other"), cursor=cursor)
    assert wrong.value.code == "CURSOR_MISMATCH"
    session.identity = "changed"
    with pytest.raises(XError) as switched:
        service.result_get(initial["result_id"])
    assert switched.value.code == "SESSION_CHANGED"
    record = service.store.get(initial["result_id"])
    record["expires"] = time.time() - 2
    expired = service.store.token(record, 1)
    with pytest.raises(XError) as error:
        service.store.decode(expired)
    assert error.value.code == "CURSOR_EXPIRED"


async def test_repeated_cursor_stops_without_duplicate_items(service_factory):
    fx = FakeProvider(
        "fxtwitter",
        {
            None: ProviderPage("fxtwitter", items=[make_post(1)], next_cursor="same"),
            "same": ProviderPage(
                "fxtwitter", items=[make_post(1), make_post(2)], next_cursor="same"
            ),
        },
    )
    service = service_factory(fx=fx)
    query = Query(operation="user.posts", target="example")
    first = await service.query(query)
    second = await service.query(query, cursor=first["page"]["next_cursor"])
    assert [p["id"] for p in second["items"]] == ["2"]
    assert second["page"]["next_cursor"] is None
    assert second["meta"]["completeness"] == "partial"


def test_result_expiration_and_cache_expiration(tmp_path):
    store = Store(tmp_path / "state")
    record = store.create(
        Query(operation="search.posts", query="a"), ProviderPage("fxtwitter"), "public"
    )
    store.cache("key", record, -1)
    assert store.cached("key") is None
    record["expires"] = 0
    store.save(record)
    with pytest.raises(XError) as error:
        store.get(record["id"])
    assert error.value.code == "RESULT_EXPIRED"
    store.close()
