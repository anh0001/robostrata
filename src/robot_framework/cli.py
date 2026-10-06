"""Command line: ``run``, ``validate`` and ``schemas export``.

Exit codes: 0 success, 1 mission finished but did not succeed, 2 framework error (printed as JSON
on stderr with a stable ``error`` code), 3 internal error (a bug; traceback in the log).
"""

import argparse
import asyncio
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from robot_framework.core.context import FrameworkContext, build_context
from robot_framework.core.errors import ContractValidationError, FrameworkError
from robot_framework.core.mission_supervisor import MissionSupervisor
from robot_framework.packages.loader import load_goal
from robot_framework.spec import GoalSpec, MissionStatus
from robot_framework.spec.export import export_schemas

EXIT_OK = 0
EXIT_MISSION_NOT_SUCCEEDED = 1
EXIT_FRAMEWORK_ERROR = 2
EXIT_INTERNAL_ERROR = 3

log = logging.getLogger(__name__)


def _goal(ctx: FrameworkContext, goal_path: Path | None) -> GoalSpec:
    if goal_path is not None:
        return load_goal(goal_path)
    if ctx.default_goal is None:
        raise ContractValidationError(
            "no goal given: pass --goal or set default_goal in the deployment profile"
        )
    return ctx.default_goal


def _cmd_run(args: argparse.Namespace) -> int:
    ctx = build_context(args.profile, record_path=args.record)
    goal = _goal(ctx, args.goal)
    result = asyncio.run(MissionSupervisor(ctx).run(goal))
    print(result.model_dump_json(indent=2))
    return EXIT_OK if result.status is MissionStatus.SUCCEEDED else EXIT_MISSION_NOT_SUCCEEDED


def _cmd_validate(args: argparse.Namespace) -> int:
    ctx = build_context(args.profile)
    goal = _goal(ctx, args.goal)
    validated = asyncio.run(MissionSupervisor(ctx).prepare(goal))
    report = {
        "status": "valid",
        "profile": str(args.profile),
        "goal_id": goal.goal_id,
        "proposal_id": validated.proposal.proposal_id,
        "artifact_kind": validated.proposal.kind.value,
        "planner": ctx.profile.planning.plugin,
        "executive": ctx.profile.execution.plugin,
        "skills": list(validated.skill_refs),
        "resource_scope": sorted(validated.resource_scope),
        "extensions": [ext.extension_id for ext in ctx.extensions],
    }
    print(json.dumps(report, indent=2))
    return EXIT_OK


def _cmd_schemas_export(args: argparse.Namespace) -> int:
    for path in export_schemas(args.directory):
        print(path)
    return EXIT_OK


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="robot-framework", description=__doc__)
    parser.add_argument(
        "--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"]
    )
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="run a mission from a deployment profile")
    run.add_argument("profile", type=Path)
    run.add_argument("--goal", type=Path, help="goal YAML (default: the profile's default_goal)")
    run.add_argument("--record", type=Path, help="append mission events to this JSONL file")
    run.set_defaults(handler=_cmd_run)

    validate = commands.add_parser("validate", help="plan and validate without executing")
    validate.add_argument("profile", type=Path)
    validate.add_argument("--goal", type=Path)
    validate.set_defaults(handler=_cmd_validate)

    schemas = commands.add_parser("schemas", help="JSON Schema tools")
    schema_commands = schemas.add_subparsers(dest="schemas_command", required=True)
    export = schema_commands.add_parser("export", help="write one JSON Schema per contract")
    export.add_argument("directory", type=Path)
    export.set_defaults(handler=_cmd_schemas_export)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level), format="%(levelname)s %(name)s: %(message)s"
    )
    try:
        return int(args.handler(args))
    except FrameworkError as exc:
        print(json.dumps(exc.to_dict(), indent=2, default=str), file=sys.stderr)
        return EXIT_FRAMEWORK_ERROR
    except Exception as exc:
        log.exception("internal error")
        error = {"error": "internal_error", "message": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(error, indent=2), file=sys.stderr)
        return EXIT_INTERNAL_ERROR


if __name__ == "__main__":
    sys.exit(main())
