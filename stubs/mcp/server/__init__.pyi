from collections.abc import Awaitable, Callable
from typing import Generic, Literal, ParamSpec, TypeVar

_LifespanT = TypeVar("_LifespanT")
_ParamsT = ParamSpec("_ParamsT")
_ReturnT = TypeVar("_ReturnT")

class MCPServer(Generic[_LifespanT]):
    """Typed subset of MCPServer used by this package."""

    def __init__(
        self,
        name: str | None = ...,
        title: str | None = ...,
        description: str | None = ...,
        instructions: str | None = ...,
        website_url: str | None = ...,
        version: str = ...,
    ) -> None: ...
    def tool(
        self,
        name: str | None = ...,
        title: str | None = ...,
        description: str | None = ...,
        *,
        structured_output: bool | None = ...,
    ) -> Callable[
        [Callable[_ParamsT, Awaitable[_ReturnT]]],
        Callable[_ParamsT, Awaitable[_ReturnT]],
    ]: ...
    def resource(
        self, uri: str
    ) -> Callable[
        [Callable[_ParamsT, Awaitable[_ReturnT]]],
        Callable[_ParamsT, Awaitable[_ReturnT]],
    ]: ...
    def run(self, transport: Literal["stdio", "sse", "streamable-http"] = ...) -> None: ...
