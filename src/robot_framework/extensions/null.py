"""Null grounding plugin: the extension hook with no opinion (NOT_APPLICABLE)."""

from robot_framework.spec import (
    AssessmentContext,
    AssessmentReport,
    AssessmentStatus,
    ProviderManifest,
    SkillInvocation,
    WorldSnapshot,
)


class NullGroundingPlugin:
    plugin_id = "null_grounding"

    async def assess(
        self, request: SkillInvocation, provider: ProviderManifest, world: WorldSnapshot
    ) -> AssessmentReport:
        return AssessmentReport(
            status=AssessmentStatus.NOT_APPLICABLE,
            reason="null grounding plugin performs no assessment",
            context=AssessmentContext(
                world_snapshot_id=world.snapshot_id,
                robot_state_revision=world.revision,
                provider_id=provider.provider_id,
            ),
        )
