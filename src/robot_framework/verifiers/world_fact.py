"""Evidence-based verifier: re-observes every expected effect on fresh evidence.

VERIFIED only when every expected fact is present, fresh, observed no earlier than the invocation
was created, and matching; any such mismatch is FAILED; otherwise (missing, stale or older
evidence) UNKNOWN. Provider claims are never consulted.
"""

from robot_framework.core.interfaces import WorldInterface
from robot_framework.spec import (
    Fact,
    SkillContract,
    SkillInvocation,
    VerificationStatus,
    bind_args,
)

_Verdict = VerificationStatus


class WorldFactVerifier:
    verifier_id = "world_fact"

    async def verify(
        self, contract: SkillContract, invocation: SkillInvocation, world: WorldInterface
    ) -> tuple[VerificationStatus, tuple[Fact, ...], tuple[str, ...]]:
        observed: tuple[Fact, ...] = ()
        verdicts: tuple[VerificationStatus, ...] = ()
        for effect in contract.expected_effects:
            args = bind_args(effect.args, invocation.bound_params)
            fact = await world.observe(effect.predicate, args)
            snapshot = world.snapshot()
            fact = fact if fact is not None else snapshot.lookup(effect.predicate, args)
            verdict = _judge(fact, effect.expected, snapshot.time, invocation.created_at)
            verdicts = (*verdicts, verdict)
            if fact is not None and verdict is not _Verdict.UNKNOWN:
                observed = (*observed, fact)
        if _Verdict.FAILED in verdicts:
            status = _Verdict.FAILED
        elif _Verdict.UNKNOWN in verdicts:
            status = _Verdict.UNKNOWN
        else:
            status = _Verdict.VERIFIED
        refs = tuple(
            f"fact:{f.predicate}({','.join(f.args)})={f.value}@rev{f.revision}" for f in observed
        )
        return status, observed, refs


def _judge(fact: Fact | None, expected: bool, now: float, not_before: float) -> VerificationStatus:
    if fact is None or fact.is_stale(now) or fact.observation_time < not_before:
        return _Verdict.UNKNOWN
    return _Verdict.VERIFIED if fact.value == expected else _Verdict.FAILED
