<div align="center">

<h1>rm-controller</h1>

<h3>Topology-aware placement for heterogeneous llm-d pools</h3>

<p>
  <strong>English</strong> · <a href="README.ko.md">한국어</a>
</p>

<p>
  <a href="https://github.com/ai-computing/ai-rm"><img src="https://img.shields.io/badge/ai--rm-L4%20cluster%20%26%20placement-fbbf24" alt="ai-rm layer L4"></a>
  <a href="https://github.com/ai-computing/rm-core/blob/v0.1.1/PROTOCOL.md"><img src="https://img.shields.io/badge/protocol-v0.1-7c5cff" alt="Protocol v0.1"></a>
  <a href="https://github.com/ai-computing/ai-rm/actions/workflows/packages.yml"><img src="https://github.com/ai-computing/ai-rm/actions/workflows/packages.yml/badge.svg" alt="packages CI"></a>
  <img src="https://img.shields.io/badge/stage-first%20version-107e72" alt="Stage: first version">
  <a href="../../LICENSE"><img src="https://img.shields.io/badge/license-BSD--3--Clause-64748b" alt="License: BSD-3-Clause"></a>
</p>

<p>
  <a href="#-quick-start"><b>Quick start</b></a> ·
  <a href="#-placement-policy"><b>Policy</b></a> ·
  <a href="#-spec"><b>Spec</b></a> ·
  <a href="#-verified"><b>Verified</b></a> ·
  <a href="#-roadmap"><b>Roadmap</b></a>
</p>

</div>

---

**rm-controller** is the L4 placement controller of [ai-rm](https://github.com/ai-computing/ai-rm). It reads the
accelerators L1 publishes (`AcceleratorProfile`) and the nodes' state, places the prefill/decode pools a spec asks for, and
writes the decisions to the `airm-placement` ConfigMap that the EPP scorer and lmd-top read (format: hetero-llm-d
`deploy/airm/README.md`, key `decisions.json`).

<table>
<tr>
<td width="33%" valign="top">
<b>🧭 Topology first</b><br>
Host-local KV paths keep prefill and decode on one node and on different cards; cordoned and NotReady nodes are never chosen.
</td>
<td width="33%" valign="top">
<b>🧮 Pools, not pods</b><br>
P:D 1:N per pool, pools placed in order without sharing a card, and an empty decision with its reason when nothing fits.
</td>
<td width="33%" valign="top">
<b>📝 Quiet when nothing changes</b><br>
The document's <code>generation</code> moves only when the decisions do, so readers are not woken by an identical rewrite.
</td>
</tr>
</table>

## 🚀 Quick start

```bash
pip install -e packages/rm-controller            # rm-core, PyYAML; [k8s] adds the in-cluster client
rm-controller --spec packages/rm-controller/examples/spec.yaml --dry-run   # print what it would write
rm-controller --spec spec.yaml --once            # write when the decisions changed (generation +1)
rm-controller --spec spec.yaml --interval 60     # keep placing
python -m rm_core.conformance airm.placements topology
```

Outside a pod it uses `kubectl` with the current kubeconfig; in a pod (`KUBERNETES_SERVICE_HOST` set) it uses the Python
client (`pip install -e "packages/rm-controller[k8s]"`). Exit status: 0 written or unchanged, 1 a pool could not be placed
(the document still records why), 2 usage or cluster errors.

## 🧭 Placement policy

Policy `topology`, entry point `airm.placements:topology`, built from what the first end-to-end run showed (ai-rm
[e2e](../../docs/e2e.md): rm-core's reference `greedy` put prefill and decode on one card of a cordoned node):

| Rule | Why |
|---|---|
| `shm`, `p2p`, `loopback` keep prefill and decode on **one node**; cards differ unless `loopback` | the KV path is host-local |
| cordoned and not-Ready nodes are skipped | a placement there cannot run |
| prefill takes the **highest peak** (for the workload's precision), decode the **most memory**; ties go to the lowest card index | compute-bound prefill, memory-bound decode, stable choices |
| `count` per role | P:D 1:N |
| pools are placed in order and never share a card | no double booking |
| nothing that fits → empty decisions with the reason | never a crash, always explainable |

`place()` keeps the rm-core per-workload contract (conformance PASS); `place_pd()` places a prefill/decode pair together.

## 📝 Spec

```yaml
namespace: llm-serving                 # where airm-placement lives (llm-d's namespace)
pools:
  - pool: llama8b-pd-pool              # InferencePool name
    model: meta-llama/Llama-3.1-8B-Instruct
    kv_transport: shm                  # airm.kv_transports name
    slo: {tpot_p90_ms: 100}
    prefill: {accelerator: furiosa.RNGD, count: 1}
    decode:  {accelerator: furiosa.RNGD, count: 1}
```

`accelerator` is `vendor.model`, as in the node labels `airm.ai-computing.io/<vendor>.<model>`. Examples:
[`examples/spec.yaml`](examples/spec.yaml) (RNGD+RNGD over shm), [`examples/hetero-p2p.yaml`](examples/hetero-p2p.yaml)
(RNGD prefill, ATOM ×2 decode over same-host P2P).

## ✅ Verified

- 12 tests on a pool shaped like the lab cluster; `rm_core.conformance airm.placements topology` PASS; CI runs both.
- Read-only dry run on the live cluster (2026-10-19): the shm pool went to `etri-001/furiosa:0` + `furiosa:1`, the placement
  the end-to-end run had pinned by hand, with the cordoned node skipped; the p2p pool went to RNGD 0 + ATOM 0, 1.

## 🗺 Roadmap

- [ ] Use live load (`airm_*` queueing, TPOT) and workload shape ([traces](../../docs/workload-traces.md)) in the choice
- [ ] Serving pods that follow the decisions (today site values still pin the same cards)
- [x] An image (`ghcr.io/ai-computing/rm-controller`, [`Dockerfile`](Dockerfile)) and a Deployment in the umbrella chart [`charts/ai-rm`](../../charts/ai-rm)
- [ ] The `airm-placement` format made normative in rm-core's protocol

## 📄 License

BSD-3-Clause, as [ai-rm](../../LICENSE).
