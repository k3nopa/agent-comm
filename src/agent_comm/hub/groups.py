"""Pure in-memory group (alias) store: group name -> set of member names.

No I/O here, same rationale as registry.py: cheap to unit test in isolation
without a running hub. Groups are in-memory only and do not persist across
hub restarts, consistent with the rest of the hub's "no persistence" design.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field


class GroupNotFound(Exception):
    pass


@dataclass
class GroupStore:
    _groups: dict[str, set[str]] = field(default_factory=dict)

    def exists(self, group: str) -> bool:
        return group in self._groups

    def get_members(self, group: str) -> set[str] | None:
        members = self._groups.get(group)
        return set(members) if members is not None else None

    def set_members(self, group: str, members: Iterable[str]) -> set[str]:
        """Create or fully replace a group's membership."""
        self._groups[group] = set(members)
        return set(self._groups[group])

    def add_members(self, group: str, members: Iterable[str]) -> set[str]:
        """Union members into a group, creating it if it doesn't exist yet."""
        self._groups.setdefault(group, set()).update(members)
        return set(self._groups[group])

    def remove_members(self, group: str, members: Iterable[str]) -> set[str]:
        """Discard members from an existing group. Raises GroupNotFound if the
        group itself doesn't exist; removing a name that isn't currently a
        member is silently tolerated.
        """
        if group not in self._groups:
            raise GroupNotFound(group)
        self._groups[group].difference_update(members)
        return set(self._groups[group])

    def delete(self, group: str) -> bool:
        """Idempotent delete. Returns True iff the group existed."""
        return self._groups.pop(group, None) is not None

    def list_groups(self) -> dict[str, list[str]]:
        return {name: sorted(members) for name, members in sorted(self._groups.items())}
