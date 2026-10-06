"""Explicit, typed registries. No import-time magic: everything is registered by name."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Generic, TypeVar, cast

from robot_framework.core.errors import ContractValidationError

T = TypeVar("T")


class Registry(Generic[T]):
    """Name → item. ``protocol`` (a class or runtime-checkable Protocol) is checked on register."""

    def __init__(self, kind: str, protocol: object | None = None) -> None:
        self._kind = kind
        self._protocol = protocol
        self._items: dict[str, T] = {}

    @property
    def kind(self) -> str:
        return self._kind

    def register(self, key: str, item: T) -> None:
        if key in self._items:
            raise ContractValidationError(
                f"duplicate {self._kind} '{key}'", details={"kind": self._kind, "key": key}
            )
        if self._protocol is not None and not isinstance(item, cast(type, self._protocol)):
            name = getattr(self._protocol, "__name__", str(self._protocol))
            raise ContractValidationError(
                f"{self._kind} '{key}' does not implement {name}",
                details={"kind": self._kind, "key": key, "expected": name},
            )
        self._items = {**self._items, key: item}

    def get(self, key: str) -> T:
        try:
            return self._items[key]
        except KeyError:
            raise KeyError(
                f"unknown {self._kind} '{key}'; registered: {sorted(self._items)}"
            ) from None

    def items(self) -> Mapping[str, T]:
        """Read-only view in registration order."""
        return MappingProxyType(self._items)

    def __contains__(self, key: object) -> bool:
        return key in self._items

    def __len__(self) -> int:
        return len(self._items)
