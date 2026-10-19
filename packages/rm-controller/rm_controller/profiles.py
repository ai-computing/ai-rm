"""Throughput profiles: what one serving instance of a device type does, and what a KV link costs.

The table (default: `profiles.yaml` next to this file, or a YAML/JSON file given with `--profiles`) is the
only performance input of the `optimal` policy and the simulator; see the file for where each number comes
from. A device type without an entry is unknown to `optimal`, which then falls back to `topology`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Tuple

import yaml

DEFAULT = Path(__file__).with_name("profiles.yaml")


@dataclass(frozen=True)
class DeviceProfile:
    kind: str                       # vendor.model
    group: int                      # cards per serving instance
    prefill_tok_s: float            # prompt tokens per second, one instance
    prefill_overhead_ms: float
    tpot_ms_b1: float               # decode time per output token at batch 1
    tpot_ms_bmax: float             # ... at max_batch (linear in between)
    max_batch: int
    kv_tokens: int                  # KV tokens one instance holds beside the weights
    source: Dict[str, str] = field(default_factory=dict)

    def prefill_ms(self, tokens: float) -> float:
        return self.prefill_overhead_ms + 1000.0 * tokens / self.prefill_tok_s

    def tpot_ms(self, batch: float) -> float:
        if self.max_batch <= 1:
            return self.tpot_ms_b1
        b = min(max(batch, 1.0), float(self.max_batch))
        return self.tpot_ms_b1 + (self.tpot_ms_bmax - self.tpot_ms_b1) * (b - 1) / (self.max_batch - 1)

    def batch_for(self, tpot_slo_ms: Optional[float]) -> int:
        """Largest batch whose TPOT meets the SLO (0 if even batch 1 misses it)."""
        if not tpot_slo_ms:
            return self.max_batch
        return max([b for b in range(1, self.max_batch + 1) if self.tpot_ms(b) <= tpot_slo_ms] or [0])

    @property
    def estimated(self) -> bool:
        return any(v == "estimate" for v in self.source.values())


@dataclass(frozen=True)
class Link:
    name: str                       # airm.kv_transports name
    scope: str                      # card | host | cluster
    gb_s: float                     # 0 = no copy
    latency_ms: float = 0.0
    min_bytes: int = 0              # bytes moved at least (shm copies the whole compiled buffer)
    implemented: bool = True
    source: str = ""
    pairs: Tuple[str, ...] = ()     # "prefill.kind->decode.kind" it works for; () = any
    admit_blocking: bool = False    # the decode side loads the KV at admission inside its loop (stalls all streams)

    def serves(self, prefill_kind: str, decode_kind: str) -> bool:
        return not self.pairs or f"{prefill_kind}->{decode_kind}" in self.pairs

    def transfer_ms(self, nbytes: float) -> float:
        if self.gb_s <= 0:
            return self.latency_ms
        return self.latency_ms + max(nbytes, self.min_bytes) / (self.gb_s * 1e9) * 1000.0


@dataclass(frozen=True)
class Profiles:
    model: str
    kv_bytes_per_token: int
    devices: Dict[str, DeviceProfile]
    links: Dict[str, Link]

    def kv_ms(self, link: Link, tokens: float) -> float:
        return link.transfer_ms(tokens * self.kv_bytes_per_token)


def parse(raw: dict) -> Profiles:
    devices = {}
    for kind, d in (raw.get("devices") or {}).items():
        devices[kind] = DeviceProfile(
            kind=kind, group=int(d.get("group", 1)), prefill_tok_s=float(d["prefill_tok_s"]),
            prefill_overhead_ms=float(d.get("prefill_overhead_ms", 0)), tpot_ms_b1=float(d["tpot_ms_b1"]),
            tpot_ms_bmax=float(d.get("tpot_ms_bmax", d["tpot_ms_b1"])), max_batch=int(d.get("max_batch", 1)),
            kv_tokens=int(d["kv_tokens"]), source={k: str(v) for k, v in (d.get("source") or {}).items()})
        if devices[kind].group < 1 or devices[kind].prefill_tok_s <= 0 or devices[kind].max_batch < 1:
            raise ValueError(f"profile {kind}: group, prefill_tok_s and max_batch must be positive")
    links = {}
    for name, l in (raw.get("links") or {}).items():
        if l.get("scope") not in ("card", "host", "cluster"):
            raise ValueError(f"link {name}: scope must be card, host or cluster")
        links[name] = Link(name=name, scope=l["scope"], gb_s=float(l.get("gb_s", 0)),
                           latency_ms=float(l.get("latency_ms", 0)), min_bytes=int(l.get("min_bytes", 0)),
                           implemented=bool(l.get("implemented", True)), source=str(l.get("source", "")),
                           pairs=tuple(str(p).replace(" ", "") for p in (l.get("pairs") or ())),
                           admit_blocking=bool(l.get("admit_blocking", False)))
    return Profiles(model=str(raw.get("model", "")), kv_bytes_per_token=int(raw.get("kv_bytes_per_token", 131072)),
                    devices=devices, links=links)


def load(path: Optional[str] = None) -> Profiles:
    p = Path(path) if path else DEFAULT
    text = p.read_text(encoding="utf-8")
    return parse(json.loads(text) if p.suffix == ".json" else (yaml.safe_load(text) or {}))
