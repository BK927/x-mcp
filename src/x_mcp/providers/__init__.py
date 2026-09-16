from typing import Protocol

from ..models import ProviderPage, Query


class Provider(Protocol):
    name: str

    def supports(self, operation: str) -> bool: ...

    async def fetch(self, query: Query, cursor: str | None = None) -> ProviderPage: ...

    async def close(self) -> None: ...
