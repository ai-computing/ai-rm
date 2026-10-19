"""Power sampling during a run, for energy and tok/J (W7 evidence).

A sampler reads the power of the system under test every `interval_s` on a background thread while
the run is in progress:

    prom   a Prometheus instant query; the sum of the result vector is the power in W.
           Default `sum(DCGM_FI_DEV_POWER_USAGE)` (NVIDIA DCGM exporter); pass the query of the NPU
           exporter in use, e.g. `sum(airm_power_w{scope="card"})`.
    cmd    any command that prints watts (furiosa-smi, rbln-stat, nvidia-smi, ipmitool ...); every
           match of `regex` in its stdout is summed. The first group is the number when the regex
           has groups. Match only the draw columns, not caps or limits.
    none   no power data; no power fields are reported.

Mean power is time-weighted (trapezoid over the samples), energy = mean W x run wall time, and
tok/J = output tokens / energy. `scope` says what was measured: `card` (accelerators only) or `node`
(the whole node), and is the `scope` tag of `power_w`/`energy_j` (rm-core requires it on power_w).
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass, field

import requests

DEFAULT_PROM_QUERY = "sum(DCGM_FI_DEV_POWER_USAGE)"
DEFAULT_REGEX = r"(\d+(?:\.\d+)?)\s*W\b"
SOURCES = ("none", "prom", "cmd")
SCOPES = ("card", "node")


@dataclass
class PowerSummary:
    source: str
    scope: str
    samples: int
    mean_w: float
    peak_w: float
    window_s: float
    energy_j: float
    out_tokens: int = 0

    @property
    def tok_per_j(self) -> float | None:
        return self.out_tokens / self.energy_j if self.energy_j > 0 else None

    def as_dict(self) -> dict:
        """The run-record fields, named like the airm_* series."""
        return {"source": self.source, "scope": self.scope, "samples": self.samples,
                "power_w": self.mean_w, "power_peak_w": self.peak_w, "energy_j": self.energy_j,
                "window_s": self.window_s, "out_tokens": self.out_tokens, "tok_per_j": self.tok_per_j}


def summarize(samples: list[tuple[float, float]], window_s: float, *, source: str, scope: str,
              out_tokens: int = 0) -> PowerSummary | None:
    """(t_s, watts) samples -> mean/peak W and energy over `window_s`. None without samples."""
    if not samples:
        return None
    samples = sorted(samples)
    span = samples[-1][0] - samples[0][0]
    if len(samples) == 1 or span <= 0:
        mean_w = sum(w for _, w in samples) / len(samples)
    else:
        area = sum((t1 - t0) * (w0 + w1) / 2.0 for (t0, w0), (t1, w1) in zip(samples, samples[1:]))
        mean_w = area / span
    window_s = max(window_s, 0.0)
    return PowerSummary(source=source, scope=scope, samples=len(samples), mean_w=mean_w,
                        peak_w=max(w for _, w in samples), window_s=window_s, energy_j=mean_w * window_s,
                        out_tokens=out_tokens)


@dataclass
class PowerSampler:
    """Base sampler: `read_w()` returns the current power in W, or None when unavailable."""
    interval_s: float = 1.0
    scope: str = "card"
    source: str = "none"
    samples: list = field(default_factory=list)
    errors: int = 0

    def __post_init__(self):
        if self.scope not in SCOPES:
            raise ValueError(f"power scope must be one of {SCOPES}")
        if self.interval_s <= 0:
            raise ValueError("power interval must be positive")
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._t0 = 0.0

    def read_w(self) -> float | None:
        raise NotImplementedError

    def _sample(self) -> None:
        try:
            w = self.read_w()
        except Exception:  # noqa: BLE001 -- a failed read loses one sample, never the run
            w = None
        if w is None:
            self.errors += 1
        else:
            self.samples.append((time.perf_counter() - self._t0, float(w)))

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            self._sample()

    def start(self) -> None:
        self.samples, self.errors = [], 0
        self._stop.clear()
        self._t0 = time.perf_counter()
        self._sample()
        self._thread = threading.Thread(target=self._loop, name="rm-bench-power", daemon=True)
        self._thread.start()

    def stop(self, window_s: float | None = None, out_tokens: int = 0) -> PowerSummary | None:
        """Stop sampling (one last sample at the end) and summarize over `window_s` (default: the
        sampling time)."""
        elapsed = time.perf_counter() - self._t0
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval_s + 30)
            self._thread = None
        self._sample()
        return summarize(self.samples, elapsed if window_s is None else window_s, source=self.source,
                         scope=self.scope, out_tokens=out_tokens)


@dataclass
class PrometheusPower(PowerSampler):
    url: str = ""
    query: str = DEFAULT_PROM_QUERY
    timeout_s: float = 5.0
    source: str = "prom"

    def __post_init__(self):
        super().__post_init__()
        if not self.url:
            raise ValueError("prom power source needs --power-url or $PROMETHEUS_URL")

    def read_w(self) -> float | None:
        resp = requests.get(self.url.rstrip("/") + "/api/v1/query", params={"query": self.query},
                            timeout=self.timeout_s)
        resp.raise_for_status()
        body = resp.json()
        if body.get("status") != "success":
            return None
        data = body.get("data") or {}
        result = data.get("result")
        if data.get("resultType") == "scalar" and isinstance(result, list):
            return float(result[1])
        if not result:
            return None
        return sum(float(r["value"][1]) for r in result)


@dataclass
class CommandPower(PowerSampler):
    command: str = ""
    regex: str = DEFAULT_REGEX
    timeout_s: float = 10.0
    source: str = "cmd"

    def __post_init__(self):
        super().__post_init__()
        if not self.command:
            raise ValueError("cmd power source needs --power-cmd")
        self._re = re.compile(self.regex)

    def parse(self, text: str) -> float | None:
        values = []
        for m in self._re.finditer(text):
            values.append(float(m.group(1) if self._re.groups else m.group(0)))
        return sum(values) if values else None

    def read_w(self) -> float | None:
        # Windows parses the command line itself; POSIX splits it like a shell would (no shell runs)
        args = self.command if os.name == "nt" else shlex.split(self.command)
        proc = subprocess.run(args, capture_output=True, text=True,
                              timeout=self.timeout_s, check=False)
        return self.parse(proc.stdout) if proc.returncode == 0 else None


def make_sampler(source: str | None, *, url: str | None = None, query: str | None = None,
                 command: str | None = None, regex: str | None = None, interval_s: float = 1.0,
                 scope: str = "card") -> PowerSampler | None:
    """Sampler for a CLI/config choice; None for `none`."""
    source = source or "none"
    if source == "none":
        return None
    if source == "prom":
        return PrometheusPower(url=url or "", query=query or DEFAULT_PROM_QUERY, interval_s=interval_s,
                               scope=scope)
    if source == "cmd":
        return CommandPower(command=command or "", regex=regex or DEFAULT_REGEX, interval_s=interval_s,
                            scope=scope)
    raise ValueError(f"power source must be one of {SOURCES}")
