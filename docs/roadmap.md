# Roadmap

| Phase | Proves | Exit criteria | Status |
|---|---|---|---|
| 1. Core contracts + mock runtime | A simple task runs without an LLM and without A-E; cancellation, resource ownership and verification work | Contract, unit, integration, conformance (architecture §14) and fault-injection suites green; coverage ≥ 80 %; README commands run as written | complete (2026-10-06) |
| 2. Pilot mobile manipulator | observe/navigate/pick/place on a simulator and the pilot robot through the same contracts | BT.CPP 4.6+ built from source; BehaviorTree.CPP executive; ROS 2 transport; Nav2 and MoveIt/MTC providers; Gazebo backend; conformance suite parametrised over mock + sim | planned |
| 3. A-E extension | assessment, evidence, preparation and recovery plug in without changing the core | `extensions/anhar_ae` passes the extension conformance tests; research profile requires it, baseline profile runs without it | planned |
| 4. Planning / policy backends | LLM, BTGenBot-2, PlanSys2 and VLA integrated in their proper roles | each adapter emits a validated artifact kind; BT XML and PDDL validators registered; VLA served through a policy provider under leases | planned |
| 5. Portability | a second, different embodiment and a second simulator; a non-manipulation use case | the same task pack runs on two robots; portability measured at goal/task/provider/policy level | planned |
| 6. Framework release | conformance suite, deployment profiles, docs, diagnostics, Studio | versioned `v1beta1` contracts; Studio and replay tooling; security review | planned |

## Phase 2 prerequisites recorded during Phase 1

- The host ships only BehaviorTree.CPP v3 from apt; Phase 2 starts with a source build of
  BehaviorTree.CPP 4.6+ (needed by BTGenBot-2 XML and BehaviorTree.ROS2).
- MoveIt Task Constructor is not installed; PlanSys2 is not installed (Phase 4).
- ROS 2 Humble reaches end of life in May 2027; nothing in the core may assume Humble.
