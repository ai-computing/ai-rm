"""ai-rm adapter: workload runner `rm-bench` (entry-point group `airm.workloads`, PROTOCOL.md §5.3).

    runner = rm_core.registry.load("airm.workloads", "rm-bench")
    result = runner(Workload(kind="serve", model="m", slo={"ttft_p90_ms": 2000}),
                    scenario="pd-smoke", gateway=os.environ["LLMD_GATEWAY_URL"])

Configuration keys (documented in README):
  scenario      (required) scenario name in scenarios/ or a .yaml path
  gateway       gateway base URL; default $LLMD_GATEWAY_URL
  out           Measurement JSON path; default results/<run_id>.json, None/"" to skip writing
  kv_transport  KV transport name configured for the serving path; recorded as a tag only

`Workload.model` is the model to request; a non-empty `Workload.slo` replaces the scenario's SLO.
"""
from __future__ import annotations

import os

from rm_core import Workload
from rm_core.errors import ContractError

from . import e2e
from .results import write_measurements
from .scenario import load_scenario

_DEFAULT = object()


class RmBenchRunner:
    name = "rm-bench"

    def __call__(self, workload: Workload, *, scenario: str, gateway: str | None = None,
                 out=_DEFAULT, kv_transport: str | None = None) -> e2e.E2EResult:
        workload.validate()
        if workload.kind != "serve":
            raise ContractError(f"rm-bench runs serve workloads, got kind={workload.kind!r}")
        sc = load_scenario(scenario)
        gateway = gateway or os.environ.get("LLMD_GATEWAY_URL", "")
        run_id = e2e.new_run_id(sc.name)
        res = e2e.run(sc, gateway, workload.model or None, slo=workload.slo or None,
                      run_id=run_id, kv_transport=kv_transport)
        if out is _DEFAULT:
            out = os.path.join("results", f"{run_id}.json")
        if out:
            write_measurements(out, res.measurements)
        return res
