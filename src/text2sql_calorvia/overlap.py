"""Payroll: two aggregates must not differ by a handful of people (step 24, D73).

Two allowed queries can isolate someone: the average of a site, then of the same site without one person. The rule on
each query can't see that, so the server remembers which rows each payroll aggregate covered, and refuses one whose
rows differ from an earlier one's by fewer people than the minimum group. Different periods share no rows and pass.
Kept in memory, bounded: a restart, or enough other queries, forgets the oldest.
"""
import threading
from collections import deque

MAX_REMEMBERED_ROWS = 500_000


class OverlapGuard:
    def __init__(self, max_rows: int = MAX_REMEMBERED_ROWS):
        self.max_rows, self.total = max_rows, 0
        self.groups: deque[tuple[str, frozenset]] = deque()
        self.people: dict[tuple[str, object], object] = {}
        self.lock = threading.Lock()

    def clear(self):
        with self.lock:
            self.groups.clear()
            self.people.clear()
            self.total = 0

    def _closest(self, table: str, rows: frozenset, minimum: int) -> int | None:
        for seen_table, seen in self.groups:
            if seen_table != table or seen == rows or seen.isdisjoint(rows):
                continue
            people = set()
            for row in seen ^ rows:
                people.add(self.people[(table, row)])
                if len(people) >= minimum:
                    break
            if 0 < len(people) < minimum:
                return len(people)
        return None

    def admit(self, table: str, groups: list[dict], minimum: int) -> int | None:
        """Record the groups ({row: person} each), or return how few people separate one from an earlier group."""
        with self.lock:
            for group in groups:
                for row, person in group.items():
                    self.people[(table, row)] = person
            sets = [frozenset(group) for group in groups]
            for rows in sets:
                if (found := self._closest(table, rows, minimum)) is not None:
                    return found
            known = {seen for seen_table, seen in self.groups if seen_table == table}
            for rows in sets:
                if rows not in known:
                    self.groups.append((table, rows))
                    self.total += len(rows)
            while self.total > self.max_rows and self.groups:
                self.total -= len(self.groups.popleft()[1])
            return None


guard = OverlapGuard()
