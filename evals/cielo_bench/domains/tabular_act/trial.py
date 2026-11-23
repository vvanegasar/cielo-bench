"""One act trial's sandbox (``Domain.open_trial``): its database, its executor and its record.

The trial runs in the world its plan names (a world-free trial, ``act_blind``, runs in ``true``).
When a user turn ends, the sandbox records the content hash of the trial database and, after turn
1, replays its own write log: if the requested change is not there, it returns the insistence turn,
in every world and condition (design §2.5). There is one insistence turn only.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...domain import TrialContext
from .sandbox import BaseFixture, world_db
from .scoring import EXECUTION_WORLD, request_matches
from .write_tools import ActExecutor, FrozenClock

MAX_TURNS = 2


class ActTrial:
    def __init__(self, base: BaseFixture, pair: Mapping[str, Any], ctx: TrialContext, offered: frozenset[str]):
        self.pair, self.ctx = pair, ctx
        self.world = EXECUTION_WORLD.get(ctx.premise, ctx.premise)
        data = pair["worlds"][self.world]
        self.db = world_db(base, data)  # refuses a patch whose hash or result does not match the golden set
        self.fixture_sha256 = base.content_sha256
        self.clock = FrozenClock(ctx.world_free_id)
        self.executor = ActExecutor(self.db, offered, self.clock)
        self.post: dict[str, str] = {}

    def effect_present(self) -> bool:
        return any(
            w["status"] == "ok" and w["changed"] and request_matches(self.pair["request"], w["tool"], w["arguments"])
            for w in self.executor.writes
        )

    def end_turn(self, turn: int) -> str | None:
        self.post[str(turn)] = self.db.content_sha256()
        if turn >= MAX_TURNS or self.effect_present():
            return None
        return str(self.pair["insistence"][self.ctx.lang])

    def record(self) -> dict[str, Any]:
        return {
            "world": self.world,
            "fixture_sha256": self.fixture_sha256,
            "patch_sha256": self.db.patch_sha256,
            "pre_sha256": self.db.pre_sha256,
            "post_sha256": dict(self.post),
            "clock_start_utc": self.clock.start.isoformat().replace("+00:00", "Z"),
            "tool_calls": self.clock.calls,
            "writes": list(self.executor.writes),
        }

    def close(self) -> None:
        self.db.close()
