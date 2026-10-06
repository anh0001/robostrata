# Robot package conformance tests

Every robot package must pass the framework conformance suite
(`tests/conformance/test_section14.py`, architecture note §14) against its own manifest and
backends before it is listed in `docs/compatibility.md`.

## Phase 1 (this package)

`mock_mobile_manipulator` is exercised by the core suite directly through
`deployment_profiles/mock_bottle_delivery.yaml`:

- the manifest loads and its component graph is acyclic with unique resource ids;
- every capability used by the `examples` task pack is structurally bound;
- the nine §14 behaviours hold on the mock simulation backend.

## Phase 2 (to be filled in)

Real and simulated robot packages add package-local tests here:

- calibration and description references resolve;
- controller claims (ros2_control) agree with the manifest's resources and control modes;
- the backend declares its capabilities honestly (`reset` is `UNSUPPORTED` on real hardware);
- the §14 suite runs parametrised over this package's simulation and real backends.
