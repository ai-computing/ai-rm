"""Scenario definitions: scenarios/<name>.yaml.

    name: pd-smoke
    model: null                 # optional; else --model / Workload.model / gateway /v1/models
    requests:
      source: synthetic         # synthetic | trace
      count: 32
      arrival: {kind: poisson, rps: 8}   # poisson | deterministic | none (all at once)
      prompt_tokens: "uniform:16,128"    # const:X | uniform:A,B | normal:MU,SIGMA | lognormal:MU,SIGMA
      max_tokens: "const:32"
      # trace: {csv: path/to/AzureLLMInferenceTrace.csv, speedup: 10}   (source: trace)
    concurrency: 8
    duration_s: 60              # stop issuing new requests after this
    timeout_s: 30               # per request
    seed: 0
    max_error_pct: 0            # verdict fails above this
    slo: {ttft_p90_ms: 2000}    # keys from rm_core.workload.SLO_KEYS

Target addresses never go here; they come from --gateway / LLMD_GATEWAY_URL.
"""
from __future__ import annotations

import csv
import os
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import yaml
from rm_core.errors import ContractError
from rm_core.workload import SLO_KEYS

# (offset_s from run start, prompt_tokens, max_tokens)
Request = tuple[float, int, int]


@dataclass
class Scenario:
    name: str
    requests: dict
    concurrency: int = 8
    duration_s: float = 60.0
    timeout_s: float = 30.0
    seed: int = 0
    max_error_pct: float = 0.0
    model: str | None = None
    description: str = ""
    slo: dict[str, float] = field(default_factory=dict)

    def validate(self) -> Scenario:
        if not isinstance(self.requests, dict) or not isinstance(self.slo, dict):
            raise TypeError(f"scenario {self.name}: requests and slo must be mappings")
        for key in ("concurrency", "duration_s", "timeout_s", "max_error_pct"):
            if isinstance(getattr(self, key), bool) or not isinstance(getattr(self, key), (int, float)):
                raise TypeError(f"scenario {self.name}: {key} must be a number")
        unknown = set(self.slo) - set(SLO_KEYS)
        if unknown:
            raise ContractError(f"scenario {self.name}: unknown SLO keys {sorted(unknown)}; allowed {SLO_KEYS}")
        if self.requests.get("source", "synthetic") not in ("synthetic", "trace"):
            raise ValueError(f"scenario {self.name}: requests.source must be synthetic or trace")
        if self.concurrency < 1 or self.duration_s <= 0 or self.timeout_s <= 0:
            raise ValueError(f"scenario {self.name}: concurrency, duration_s and timeout_s must be positive")
        return self

    def schedule(self) -> list[Request]:
        """The request list, deterministic for the scenario's seed."""
        if self.requests.get("source", "synthetic") == "trace":
            return _trace_schedule(self.requests, self.duration_s)
        return _synthetic_schedule(self.requests, random.Random(self.seed))


def scenario_dirs() -> list[Path]:
    dirs = [Path(d) for d in os.environ.get("RM_BENCH_SCENARIOS", "").split(os.pathsep) if d]
    dirs.append(Path.cwd() / "scenarios")
    dirs.append(Path(__file__).resolve().parents[1] / "scenarios")  # source checkout / editable install
    return dirs


def find_scenario(name_or_path: str) -> Path:
    p = Path(name_or_path)
    if p.suffix in (".yaml", ".yml") and p.is_file():
        return p
    for d in scenario_dirs():
        cand = d / f"{name_or_path}.yaml"
        if cand.is_file():
            return cand
    raise FileNotFoundError(f"scenario {name_or_path!r} not found in {[str(d) for d in scenario_dirs()]}")


def load_scenario(name_or_path: str) -> Scenario:
    path = find_scenario(name_or_path)
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise TypeError(f"{path}: expected a mapping")
    raw.setdefault("name", path.stem)
    if "requests" not in raw:
        raise ValueError(f"{path}: missing 'requests'")
    known = set(Scenario.__dataclass_fields__)
    extra = set(raw) - known
    if extra:
        raise ValueError(f"{path}: unknown keys {sorted(extra)}")
    return Scenario(**raw).validate()


def parse_distribution(spec, rng: random.Random) -> Callable[[], float]:
    """Same spec strings as loadgen/synthetic_load_llm.py (const/uniform/normal/lognormal)."""
    if isinstance(spec, (int, float)):
        return lambda: float(spec)
    kind, _, params = str(spec).partition(":")
    args = [float(p) for p in params.split(",") if p.strip()]
    kind = kind.strip().lower()
    if kind in ("const", "constant"):
        return lambda: args[0]
    if kind == "uniform":
        return lambda: rng.uniform(args[0], args[1])
    if kind == "normal":
        return lambda: max(0.0, rng.gauss(args[0], args[1]))
    if kind == "lognormal":
        return lambda: rng.lognormvariate(args[0], args[1])
    raise ValueError(f"unknown distribution {spec!r}")


def _synthetic_schedule(req: dict, rng: random.Random) -> list[Request]:
    count = int(req.get("count", 0))
    if count < 1:
        raise ValueError("requests.count must be >= 1 for a synthetic scenario")
    prompt = parse_distribution(req.get("prompt_tokens", "const:32"), rng)
    max_tok = parse_distribution(req.get("max_tokens", "const:32"), rng)
    arrival = req.get("arrival") or {"kind": "none"}
    kind = arrival.get("kind", "none")
    rps = float(arrival.get("rps", 0) or 0)
    if kind in ("poisson", "deterministic") and rps <= 0:
        raise ValueError(f"arrival {kind} needs rps > 0")
    out, t = [], 0.0
    for _ in range(count):
        out.append((t, max(1, round(prompt())), max(1, round(max_tok()))))
        if kind == "poisson":
            t += rng.expovariate(rps)
        elif kind == "deterministic":
            t += 1.0 / rps
        elif kind != "none":
            raise ValueError(f"unknown arrival kind {kind!r}")
    return out


def _parse_ts_s(ts: str) -> float:
    dt = datetime.fromisoformat(ts.strip().replace(" ", "T"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _trace_schedule(req: dict, duration_s: float | None = None) -> list[Request]:
    """Azure LLM inference trace CSV (TIMESTAMP, ContextTokens, GeneratedTokens), time-compressed.

    Reading stops at `count` rows or at the first row past `duration_s`, whichever comes first.
    """
    trace = req.get("trace") or {}
    path = os.path.expanduser(str(trace.get("csv", "")))
    if not path:
        raise ValueError("requests.trace.csv is required for source: trace")
    speedup = float(trace.get("speedup", 1.0))
    limit = req.get("count")
    out: list[Request] = []
    t0 = None
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            ts = _parse_ts_s(row["TIMESTAMP"])
            t0 = ts if t0 is None else t0
            offset = (ts - t0) / speedup
            if duration_s is not None and offset >= duration_s:
                break
            out.append((offset, int(row["ContextTokens"]), int(row["GeneratedTokens"])))
            if limit and len(out) >= int(limit):
                break
    return out
