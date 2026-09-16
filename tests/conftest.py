from copy import deepcopy

import pytest

from x_mcp.config import Settings
from x_mcp.errors import XError
from x_mcp.models import ProviderPage
from x_mcp.service import ALL_OPERATIONS, Service


def make_post(ident="100", text="Public post #MCP https://example.com", **updates):
    return {
        "kind": "post",
        "id": str(ident),
        "url": f"https://x.com/example/status/{ident}",
        "author": {"id": "10", "handle": "example", "name": "Example"},
        "created_at": "2026-09-16T01:00:00Z",
        "text": text,
        "metrics": {"likes": 2, "reposts": 1, "replies": None, "views": None},
        **updates,
    }


def raw_user(**updates):
    return {"id": "10", "screen_name": "example", "name": "Example", "protected": False, **updates}


def raw_post(ident="100", **updates):
    return {
        "id": str(ident),
        "author": raw_user(),
        "text": "Hello",
        "created_timestamp": 1700000000,
        "likes": 1,
        **updates,
    }


class FakeProvider:
    def __init__(self, name, pages=None, *, configured=True, operations=None):
        self.name, self.pages = name, pages or {}
        self.configured = configured
        self.installed = True
        self.operations = set(ALL_OPERATIONS if operations is None else operations)
        self.calls = []
        self.identity = "session-one"

    def context(self):
        return self.identity

    def supports(self, operation):
        return operation in self.operations

    async def fetch(self, query, cursor=None):
        self.calls.append((query, cursor))
        item = self.pages.get(cursor, ProviderPage(self.name, items=[]))
        if isinstance(item, XError):
            raise item
        page = deepcopy(item)
        page.provider = self.name
        return page

    async def close(self):
        pass


@pytest.fixture
def service_factory(tmp_path):
    made = []

    def create(fx=None, session=None, max_bytes=12288):
        service = Service(
            Settings(state_dir=tmp_path / f"state-{len(made)}", max_result_bytes=max_bytes),
            fx=fx or FakeProvider("fxtwitter"),
            session=session or FakeProvider("twscrape", configured=False),
        )
        made.append(service)
        return service

    yield create
    for service in made:
        service.store.close()
