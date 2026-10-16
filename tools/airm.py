#!/usr/bin/env python3
"""ai-rm umbrella tool: list, set up, test, deploy and check the components declared by ai-rm.yaml.

    python3 tools/airm.py list
    python3 tools/airm.py doctor
    python3 tools/airm.py setup  [--layer L] [COMPONENT ...]
    python3 tools/airm.py test   [--layer L] [COMPONENT ...]
    python3 tools/airm.py deploy --cluster NAME [--dry-run] [--layer L] [COMPONENT ...]
    python3 tools/airm.py check
    python3 tools/airm.py bump COMPONENT [--ref REF]

Components live under components/<layer>/<name> as git submodules; each declares itself in
<name>/ai-rm.yaml (docs/component-contract.md). Needs Python 3.8+ and PyYAML.
"""
import argparse
import os
import shlex
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAYERS = ["l1-accel", "l2-memory", "l3-serving", "l4-cluster", "l5-ops"]


def load_yaml(path):
    try:
        import yaml
    except ImportError:
        sys.exit("PyYAML is required: python3 -m pip install pyyaml")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def components(layer=None, names=None):
    found = []
    for lay in LAYERS:
        base = os.path.join(ROOT, "components", lay)
        if not os.path.isdir(base) or (layer and lay != layer):
            continue
        for name in sorted(os.listdir(base)):
            path = os.path.join(base, name)
            if not os.path.isdir(path) or name.startswith("."):
                continue
            manifest = os.path.join(path, "ai-rm.yaml")
            spec = load_yaml(manifest) if os.path.exists(manifest) else {}
            found.append({"name": name, "layer": lay, "path": path, "spec": spec,
                          "fetched": bool(os.listdir(path))})
    if names:
        unknown = set(names) - {c["name"] for c in found}
        if unknown:
            sys.exit("unknown component(s): " + ", ".join(sorted(unknown)))
        found = [c for c in found if c["name"] in names]
    return found


def git(*args, cwd=ROOT):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True).stdout.strip()


def run_steps(comp, steps, env):
    for step in steps or []:
        print(f"  $ {step}")
        rc = subprocess.run(step, shell=True, cwd=comp["path"], env=env).returncode
        if rc != 0:
            print(f"  ! {comp['name']}: exited {rc}")
            return False
    return True


def load_env_file(path):
    env = {}
    if path and os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def cmd_list(args):
    rows = [("LAYER", "COMPONENT", "KIND", "MATURITY", "VERSION", "DEPLOY", "MANIFEST")]
    for c in components(args.layer):
        s = c["spec"]
        version = git("describe", "--tags", "--always", cwd=c["path"]) if c["fetched"] else "(not fetched)"
        deploy = (s.get("deploy") or {})
        target = deploy.get("target") or "-"
        if deploy.get("manifests"):
            target += " ✓"
        rows.append((c["layer"], c["name"], s.get("kind", "?"), s.get("maturity", "?"), version[:24],
                     target, "yes" if s else ("missing" if c["fetched"] else "-")))
    widths = [max(len(str(r[i])) for r in rows) for i in range(len(rows[0]))]
    for r in rows:
        print("  ".join(str(v).ljust(w) for v, w in zip(r, widths)))


def cmd_doctor(_args):
    ok = True
    for tool, why in [("git", "submodules"), ("python3", "components"), ("kubectl", "deploy"),
                      ("helm", "llm-d charts"), ("cargo", "lmd-top build"), ("docker", "images")]:
        found = shutil.which(tool)
        print(f"{'ok ' if found else '-- '} {tool:8} {found or 'not found'}  ({why})")
        ok &= bool(found) or tool in ("cargo", "docker", "helm")
    missing = [c["name"] for c in components() if not c["fetched"]]
    if missing:
        print("-- submodules not fetched: " + ", ".join(missing) +
              "\n   run: git submodule update --init  (needs ai-computing org access)")
    if not os.path.exists(os.path.join(ROOT, "deploy", "clusters", "local", "cluster.local.env")):
        print("-- deploy/clusters/local/cluster.local.env not found (copy deploy/clusters/example/cluster.example.env)")
    return 0 if ok else 1


def cmd_setup(args, phase="install"):
    failed = []
    for c in components(args.layer, args.components):
        if not c["fetched"]:
            print(f"[{c['name']}] not fetched; skipped")
            continue
        steps = c["spec"].get(phase)
        print(f"[{c['name']}] {phase}: {len(steps or [])} step(s)")
        if not run_steps(c, steps, os.environ.copy()):
            failed.append(c["name"])
    if failed:
        print("failed: " + ", ".join(failed))
    return 1 if failed else 0


def cmd_deploy(args):
    cluster_dir = os.path.join(ROOT, "deploy", "clusters", args.cluster)
    env = os.environ.copy()
    env.update(load_env_file(os.path.join(cluster_dir, "cluster.local.env")))
    for c in components(args.layer, args.components):
        dep = c["spec"].get("deploy") or {}
        manifests = dep.get("manifests")
        if not manifests:
            print(f"[{c['name']}] no manifests (target: {dep.get('target', 'none')}); skipped")
            continue
        path = os.path.join(c["path"], manifests)
        kustomize = os.path.exists(os.path.join(path, "kustomization.yaml"))
        overlay = os.path.join(cluster_dir, c["name"])
        if os.path.isdir(overlay):
            path, kustomize = overlay, True
        cmd = ["kubectl", "apply", "-k" if kustomize else "-f", path]
        if args.dry_run:
            cmd.append("--dry-run=client")
        print(f"[{c['name']}] $ {' '.join(shlex.quote(x) for x in cmd)}")
        if subprocess.run(cmd, env=env).returncode != 0:
            return 1
    return 0


def cmd_check(_args):
    targets = [ROOT] + [c["path"] for c in components() if c["fetched"]]
    return subprocess.run([sys.executable, os.path.join(ROOT, "tools", "check_sensitive.py"), *targets]).returncode


def cmd_bump(args):
    [c] = components(names=[args.component])
    ref = args.ref or "origin/HEAD"
    subprocess.run(["git", "fetch", "--tags", "origin"], cwd=c["path"], check=True)
    subprocess.run(["git", "checkout", "-q", ref], cwd=c["path"], check=True)
    rel = os.path.relpath(c["path"], ROOT)
    subprocess.run(["git", "add", rel], cwd=ROOT, check=True)
    print(f"{c['name']} -> {git('rev-parse', '--short', 'HEAD', cwd=c['path'])}; commit ai-rm to record it")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("list", "doctor", "check"):
        s = sub.add_parser(name)
        s.add_argument("--layer", choices=LAYERS)
    for name in ("setup", "test"):
        s = sub.add_parser(name)
        s.add_argument("--layer", choices=LAYERS)
        s.add_argument("components", nargs="*")
    s = sub.add_parser("deploy")
    s.add_argument("--cluster", required=True)
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--layer", choices=LAYERS)
    s.add_argument("components", nargs="*")
    s = sub.add_parser("bump")
    s.add_argument("component")
    s.add_argument("--ref")
    args = ap.parse_args()
    if args.cmd == "list":
        return cmd_list(args)
    if args.cmd == "doctor":
        return cmd_doctor(args)
    if args.cmd == "setup":
        return cmd_setup(args, "install")
    if args.cmd == "test":
        return cmd_setup(args, "test")
    if args.cmd == "deploy":
        return cmd_deploy(args)
    if args.cmd == "check":
        return cmd_check(args)
    if args.cmd == "bump":
        return cmd_bump(args)


if __name__ == "__main__":
    sys.exit(main() or 0)
