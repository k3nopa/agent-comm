"""Pure in-memory registry of connected names -> connection handles.

No I/O here on purpose: this is the part of the hub that's cheap to unit test
without spinning up a real websocket server.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Generic, TypeVar

ConnT = TypeVar("ConnT")


@dataclass
class Registration(Generic[ConnT]):
    name: str
    conn_id: str
    conn: ConnT


class NameTaken(Exception):
    pass


@dataclass
class Registry(Generic[ConnT]):
    _by_name: dict[str, Registration[ConnT]] = field(default_factory=dict)

    def peers(self, exclude: str | None = None) -> list[str]:
        return [n for n in self._by_name if n != exclude]

    def is_connected(self, name: str) -> bool:
        return name in self._by_name

    def register(self, name: str, conn: ConnT) -> Registration[ConnT]:
        if name in self._by_name:
            raise NameTaken(name)
        reg = Registration(name=name, conn_id=uuid.uuid4().hex, conn=conn)
        self._by_name[name] = reg
        return reg

    def unregister(self, name: str) -> None:
        self._by_name.pop(name, None)

    def get(self, name: str) -> Registration[ConnT] | None:
        return self._by_name.get(name)
