"""Mock simulation backend: declares reset/step/pause. A reset bumps the execution epoch (dropping
every queued old-epoch command) and invalidates the world.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from robot_framework.core.resource_manager import CommandAuthority, ResourceManager
from robot_framework.core.world_interface import InMemoryWorld
from robot_framework.robot_backends.mock import MockGroundTruth, MockRobotBackend

if TYPE_CHECKING:
    from robot_framework.core.recorder import MissionRecorder

SIM_RESET = "sim_reset"


class MockSimulationBackend(MockRobotBackend):
    def __init__(
        self,
        authority: CommandAuthority,
        resources: ResourceManager,
        world: InMemoryWorld,
        ground_truth: MockGroundTruth | None = None,
        *,
        recorder: MissionRecorder | None = None,
        backend_id: str = "mock_sim",
    ) -> None:
        super().__init__(authority, ground_truth, recorder=recorder, backend_id=backend_id)
        self._resources = resources
        self._world = world

    def capabilities(self) -> frozenset[str]:
        return frozenset({"dispatch", "reset", "step", "pause"})

    async def reset(self) -> int:
        epoch = self._resources.bump_epoch(SIM_RESET)
        self.ground_truth.reset()
        revision = self._world.invalidate_all(SIM_RESET)
        if self._recorder is not None:
            self._recorder.record(
                "epoch_bumped", {"epoch": epoch, "reason": SIM_RESET, "world_revision": revision}
            )
        return epoch

    async def step(self) -> None:
        if self._recorder is not None:
            self._recorder.record("sim_step", {"backend_id": self.backend_id})

    async def pause(self) -> None:
        if self._recorder is not None:
            self._recorder.record("sim_pause", {"backend_id": self.backend_id})
