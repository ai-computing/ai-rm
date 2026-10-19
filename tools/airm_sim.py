"""Simulated ai-rm cluster on kind: rm-core's sim accelerators, rm-controller, a fake PD pool, rm-bench.

    python3 tools/airm.py up-sim                 # kind cluster airm-sim (2 nodes), images built and loaded,
                                                 # charts/ai-rm installed with ci/sim-values.yaml
    python3 tools/airm.py e2e-sim                # rm-controller once, airm-placement checked,
                                                 # rm-bench pd-smoke against tools/fake_openai.py
    python3 tools/airm.py e2e-sim --no-cluster   # the same checks in-process, without kind
    python3 tools/airm.py down-sim

up-sim needs docker, kind, kubectl, helm and the rm-accel submodule (git submodule update --init
components/l1-accel/rm-accel). e2e-sim needs rm-bench (pip install -e packages/rm-bench), and with
--no-cluster also rm-controller (pip install -e packages/rm-controller).
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time

import fake_openai

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLUSTER = "airm-sim"
NAMESPACE = "airm"
RELEASE = "airm"
CHART = os.path.join(ROOT, "charts", "ai-rm")
VALUES = os.path.join(CHART, "ci", "sim-values.yaml")
NODE_SRC = os.path.join(ROOT, "components", "l1-accel", "rm-accel")
IMAGES = {"airm/rm-accel:sim": NODE_SRC,
          "airm/rm-controller:sim": os.path.join(ROOT, "packages", "rm-controller")}
SCENARIO = os.path.join(ROOT, "packages", "rm-bench", "scenarios", "pd-smoke.yaml")
SIM_MODEL = "sim-model"
DEVICES_PER_NODE = 2          # rm-core SimAcceleratorProvider default: one RNGD, one ATOM
HOST_LOCAL = ("shm", "p2p", "loopback")
KIND_CONFIG = """kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
  - role: worker
"""


def sh(cmd, check=True, capture=False, stdin=None, timeout=900):
    print("$ " + " ".join(cmd), flush=True)
    p = subprocess.run(cmd, input=stdin, capture_output=capture, text=True, timeout=timeout)
    if check and p.returncode != 0:
        detail = (p.stderr or p.stdout or "").strip() if capture else ""
        raise SystemExit(f"failed ({p.returncode}): {' '.join(cmd)}" + (f"\n{detail}" if detail else ""))
    return p


def kubectl_json(*args):
    return json.loads(sh(["kubectl", "--context", f"kind-{CLUSTER}", *args, "-o", "json"], capture=True).stdout)


def require(*tools):
    missing = [t for t in tools if not shutil.which(t)]
    if missing:
        raise SystemExit("missing tools: " + ", ".join(missing) + " (see docs/getting-started.md, simulated cluster)")


def sim_pools():
    import yaml
    with open(VALUES, encoding="utf-8") as f:
        return yaml.safe_load(f)["controller"]["pools"]


# -- checks (pure, unit-tested in tools/tests) ---------------------------------------------------------

def check_placement(doc, pools, devices, min_nodes=1):
    """Problems with an airm-placement document for `pools`; [] when it is as expected.

    devices: accelerator id -> (node, "vendor.model"), from the AcceleratorProfiles.
    Expected: every pool has one prefill and one decode decision with `count` cards of the requested kind,
    on one node for a host-local KV transport, no card used twice, and the pools spread over at least
    `min_nodes` nodes.
    """
    errs = []
    if doc.get("protocol") != "0.1" or int(doc.get("generation") or 0) < 1:
        errs.append(f"document not written by rm-controller: protocol={doc.get('protocol')} "
                    f"generation={doc.get('generation')}")
    decisions = doc.get("decisions") or []
    seen, nodes_used = {}, set()
    for p in pools:
        name = p["pool"]
        mine = [d for d in decisions if d.get("pool") == name]
        roles = sorted(d.get("workload", {}).get("kind", "?") for d in mine)
        if roles != ["decode", "prefill"]:
            errs.append(f"{name}: roles {roles}, expected ['decode', 'prefill']")
            continue
        pool_nodes = set()
        for d in mine:
            role = d["workload"]["kind"]
            want = p[role]
            ids = d.get("acceleratorIds") or []
            if len(ids) != int(want.get("count", 1)):
                errs.append(f"{name}/{role}: {len(ids)} card(s) {ids}, expected {want.get('count', 1)} "
                            f"({d.get('reason', '')})")
            if d.get("kvTransport") != p["kv_transport"]:
                errs.append(f"{name}/{role}: kvTransport {d.get('kvTransport')}, expected {p['kv_transport']}")
            for i in ids:
                if i not in devices:
                    errs.append(f"{name}/{role}: {i} is not an AcceleratorProfile")
                    continue
                node, kind = devices[i]
                pool_nodes.add(node)
                if want.get("accelerator") and kind != want["accelerator"]:
                    errs.append(f"{name}/{role}: {i} is {kind}, expected {want['accelerator']}")
                if i in seen and seen[i] != (name, role):
                    errs.append(f"{name}/{role}: {i} already placed for {seen[i][0]}/{seen[i][1]}")
                seen[i] = (name, role)
        if p["kv_transport"] in HOST_LOCAL and len(pool_nodes) > 1:
            errs.append(f"{name}: {p['kv_transport']} needs one node, got {sorted(pool_nodes)}")
        nodes_used |= pool_nodes
    if len(nodes_used) < min_nodes:
        errs.append(f"pools use {len(nodes_used)} node(s) {sorted(nodes_used)}, expected at least {min_nodes}")
    return errs


def check_bench(measurements, rc):
    """Problems with an rm-bench result; [] when the run passed with no failed request."""
    errs = [] if rc == 0 else [f"rm-bench exited {rc}"]
    by_name = {m["name"]: m["value"] for m in measurements}
    if by_name.get("slo_attainment_pct") != 100.0:
        errs.append(f"slo_attainment_pct {by_name.get('slo_attainment_pct')}, expected 100 (0 errors)")
    if not by_name.get("tok_s"):
        errs.append("no tokens received")
    return errs


# -- steps ----------------------------------------------------------------------------------------------

def devices_from_profiles(items):
    return {o["spec"]["id"]: (o["spec"]["node"], f"{o['spec']['vendor']}.{o['spec']['model']}") for o in items}


def wait_profiles(timeout_s=240):
    nodes = [n["metadata"]["name"] for n in kubectl_json("get", "nodes")["items"]]
    want = len(nodes) * DEVICES_PER_NODE
    deadline = time.time() + timeout_s
    while True:
        items = kubectl_json("get", "acceleratorprofiles")["items"]
        print(f"AcceleratorProfiles: {len(items)}/{want} on {len(nodes)} node(s)", flush=True)
        if len(items) >= want:
            return items, nodes
        if time.time() > deadline:
            raise SystemExit(f"timed out waiting for {want} AcceleratorProfiles")
        time.sleep(5)


def cmd_up(args):
    require("docker", "kind", "kubectl", "helm")
    if not os.path.exists(os.path.join(NODE_SRC, "Dockerfile")):
        raise SystemExit("rm-accel not fetched (or older than its Dockerfile): "
                         "git submodule update --init components/l1-accel/rm-accel")
    clusters = sh(["kind", "get", "clusters"], capture=True).stdout.split()
    if CLUSTER not in clusters:
        sh(["kind", "create", "cluster", "--name", CLUSTER, "--config", "-", "--wait", "120s"], stdin=KIND_CONFIG)
    for tag, ctx in IMAGES.items():
        sh(["docker", "build", "-t", tag, ctx])
        sh(["kind", "load", "docker-image", "--name", CLUSTER, tag])
    sh(["helm", "dependency", "update", CHART])
    sh(["helm", "upgrade", "--install", RELEASE, CHART, "--kube-context", f"kind-{CLUSTER}",
        "-n", NAMESPACE, "--create-namespace", "-f", VALUES, "--wait", "--timeout", "5m"])
    items, nodes = wait_profiles()
    for o in items:
        s = o["spec"]
        print(f"  {s['id']:40} {s['vendor']}.{s['model']}")
    print(f"up-sim: {len(items)} AcceleratorProfiles on {len(nodes)} nodes; next: python3 tools/airm.py e2e-sim")
    return 0


def run_bench(out):
    if importlib.util.find_spec("rm_bench") is None:
        raise SystemExit("rm-bench is not installed: python3 -m pip install -e packages/rm-bench")
    srv = fake_openai.serve(model=SIM_MODEL)
    gateway = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        rc = sh([sys.executable, "-m", "rm_bench.cli", "e2e", "--scenario", SCENARIO, "--gateway", gateway,
                 "--out", out, "--kv-transport", "shm"], check=False).returncode
    finally:
        srv.shutdown()
    measurements = []
    if os.path.exists(out):
        with open(out, encoding="utf-8") as f:
            measurements = json.load(f)
    return check_bench(measurements, rc)


def cmd_e2e(args):
    pools = sim_pools()
    if args.no_cluster:
        from rm_core.reference import SimAcceleratorProvider
        from rm_controller import controller, document
        nodes = ["sim-node-a", "sim-node-b"]
        accs = [a for n in nodes for a in SimAcceleratorProvider(n).discover()]
        entries, unplaced = controller.plan({"namespace": NAMESPACE, "pools": pools}, accs, set())
        doc = document.build(entries, document.parse(None), "topology")[0].to_dict()
        devices = {a.id: (a.node, f"{a.vendor}.{a.model}") for a in accs}
        print(f"rm-controller (in-process): {len(accs)} sim accelerators on {len(nodes)} nodes, "
              f"{len(entries)} decisions" + (f"; not placed: {', '.join(unplaced)}" if unplaced else ""))
    else:
        require("kubectl")
        items, nodes = wait_profiles(timeout_s=60)
        devices = devices_from_profiles(items)
        rc = sh(["kubectl", "--context", f"kind-{CLUSTER}", "-n", NAMESPACE, "exec", f"deploy/{RELEASE}-rm-controller",
                 "--", "rm-controller", "--spec", "/etc/rm-controller/spec.yaml", "--once"], check=False).returncode
        if rc != 0:
            raise SystemExit(f"rm-controller --once exited {rc}")
        cm = kubectl_json("-n", NAMESPACE, "get", "configmap", "airm-placement")
        doc = json.loads(cm["data"]["decisions.json"])
    print(json.dumps(doc, indent=2))
    errs = check_placement(doc, pools, devices, min_nodes=min(len(pools), len(nodes)))
    out = args.out or os.path.join(ROOT, "results", "sim-e2e.json")
    errs += run_bench(out)
    if errs:
        print("e2e-sim FAILED:\n  " + "\n  ".join(errs))
        return 1
    print(f"e2e-sim PASS: {len(pools)} pools placed (prefill + decode) on {len(nodes)} nodes, "
          f"rm-bench pd-smoke 0 errors -> {os.path.relpath(out, ROOT)}")
    return 0


def cmd_down(_args):
    require("kind")
    sh(["kind", "delete", "cluster", "--name", CLUSTER])
    return 0
