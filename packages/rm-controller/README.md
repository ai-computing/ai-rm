# rm-controller

ai-rm L4 placement controller. It reads the accelerators L1 publishes (`AcceleratorProfile`) and node state,
places the prefill/decode pools a spec asks for, and writes the decisions to the `airm-placement` ConfigMap
that the EPP scorer and lmd-top read (format: llm-d-setup `deploy/airm/README.md`).

```bash
pip install -e packages/rm-controller           # rm-core, PyYAML; [k8s] adds the in-cluster client
rm-controller --spec packages/rm-controller/examples/spec.yaml --dry-run   # print what it would write
rm-controller --spec spec.yaml --once           # write when the decisions changed (generation +1)
rm-controller --spec spec.yaml --interval 60    # keep placing
python -m rm_core.conformance airm.placements topology
```

Policy `topology` (entry point `airm.placements:topology`), built from what the first end-to-end run showed
(ai-rm `docs/e2e.md`; rm-core's `greedy` put prefill and decode on one card of a cordoned node):

- host-local KV paths (`shm`, `p2p`, `loopback`) keep prefill and decode on one node; cards differ unless `loopback`;
- cordoned and not-Ready nodes are skipped;
- prefill takes the highest peak, decode the most memory; ties go to the lowest card index;
- `count` per role gives P:D 1:N; pools are placed in order and never share a card;
- nothing that fits gives empty decisions with the reason (exit status 1), never a crash.

Not yet: live load (`airm_*` metrics) in the choice, actuating the serving pods from the decisions (today the
site values pin the same cards), and an image/chart for running it in the cluster.
