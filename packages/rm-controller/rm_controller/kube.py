"""Cluster reads and the one write, through kubectl (the default) or the Python client in a pod.

Reads: AcceleratorProfiles (L1) with their health, nodes (cordoned, not Ready, under pressure), the
airm-placement ConfigMap, and with --apply the annotated Deployments.
Writes: that ConfigMap; with --apply, patches to those Deployments.
"""
from __future__ import annotations

import dataclasses
import json
import os
import subprocess
from typing import List, Optional, Set

from rm_core import Accelerator, k8s

from . import document
from .apply import POOL_ANNOTATION
from .policy import HEALTH_KEY

PRESSURE = ("DiskPressure", "MemoryPressure", "PIDPressure", "NetworkUnavailable")


class Kubectl:
    def __init__(self, kubectl: str = "kubectl", timeout_s: float = 60):
        self.kubectl, self.timeout_s = kubectl, timeout_s

    def _run(self, args: List[str], stdin: Optional[str] = None) -> str:
        p = subprocess.run([self.kubectl, f"--request-timeout={int(self.timeout_s)}s", *args], input=stdin,
                           capture_output=True, text=True, timeout=self.timeout_s + 10)
        if p.returncode != 0:
            raise RuntimeError(f"kubectl {' '.join(args)}: {p.stderr.strip() or p.stdout.strip()}")
        return p.stdout

    def profiles(self) -> List[Accelerator]:
        items = json.loads(self._run(["get", "acceleratorprofiles", "-o", "json"]))["items"]
        return [profile(o) for o in items]

    def unschedulable_nodes(self) -> Set[str]:
        return _unschedulable(json.loads(self._run(["get", "nodes", "-o", "json"]))["items"])

    def placement_configmap(self, namespace: str) -> Optional[dict]:
        try:
            return json.loads(self._run(["-n", namespace, "get", "configmap", document.CONFIGMAP, "-o", "json"]))
        except RuntimeError as e:
            if "NotFound" in str(e) or "not found" in str(e):
                return None
            raise

    def apply(self, obj: dict) -> None:
        self._run(["apply", "-f", "-"], stdin=json.dumps(obj))

    def deployments(self, namespace: str) -> List[dict]:
        items = json.loads(self._run(["-n", namespace, "get", "deployments", "-o", "json"]))["items"]
        return [d for d in items if POOL_ANNOTATION in ((d.get("metadata") or {}).get("annotations") or {})]

    def patch_deployment(self, namespace: str, name: str, patch: dict) -> None:
        self._run(["-n", namespace, "patch", "deployment", name, "--type", "merge", "-p", json.dumps(patch)])


class Client:
    """In-cluster access with the kubernetes package (pip install rm-controller[k8s])."""

    def __init__(self):
        from kubernetes import client, config
        config.load_incluster_config() if os.environ.get("KUBERNETES_SERVICE_HOST") else config.load_kube_config()
        self.core = client.CoreV1Api()
        self.custom = client.CustomObjectsApi()
        self.apps = client.AppsV1Api()
        self.api = client.ApiClient()

    def profiles(self) -> List[Accelerator]:
        res = self.custom.list_cluster_custom_object("airm.ai-computing.io", "v1alpha1", "acceleratorprofiles")
        return [profile(o) for o in res["items"]]

    def unschedulable_nodes(self) -> Set[str]:
        return _unschedulable(self.api.sanitize_for_serialization(self.core.list_node())["items"])

    def placement_configmap(self, namespace: str) -> Optional[dict]:
        from kubernetes.client.rest import ApiException
        try:
            return self.api.sanitize_for_serialization(
                self.core.read_namespaced_config_map(document.CONFIGMAP, namespace))
        except ApiException as e:
            if e.status == 404:
                return None
            raise

    def apply(self, obj: dict) -> None:
        from kubernetes.client.rest import ApiException
        ns, name = obj["metadata"]["namespace"], obj["metadata"]["name"]
        try:
            self.core.patch_namespaced_config_map(name, ns, obj)
        except ApiException as e:
            if e.status != 404:
                raise
            self.core.create_namespaced_config_map(ns, obj)

    def deployments(self, namespace: str) -> List[dict]:
        items = self.api.sanitize_for_serialization(self.apps.list_namespaced_deployment(namespace))["items"]
        return [d for d in items if POOL_ANNOTATION in ((d.get("metadata") or {}).get("annotations") or {})]

    def patch_deployment(self, namespace: str, name: str, patch: dict) -> None:
        self.apps.patch_namespaced_deployment(name, namespace, patch)


def profile(obj: dict) -> Accelerator:
    """An Accelerator from an AcceleratorProfile, with `extra["health"] = "unhealthy"` when the profile's
    status says so (`status.health`/`status.healthy`, or a Healthy/Ready condition that is not True)."""
    acc = k8s.from_profile(obj)
    st = obj.get("status") or {}
    bad = str(st.get("health", "")).lower() in ("unhealthy", "failed", "error") or st.get("healthy") is False
    bad = bad or any(c.get("type") in ("Healthy", "Ready") and c.get("status") not in ("True", True)
                     for c in st.get("conditions") or [])
    return dataclasses.replace(acc, extra={**acc.extra, HEALTH_KEY: "unhealthy"}) if bad else acc


def _unschedulable(nodes: List[dict]) -> Set[str]:
    """Nodes that are cordoned, not Ready, or report disk/memory/PID pressure or no network."""
    out = set()
    for n in nodes:
        conds = (n.get("status") or {}).get("conditions") or []
        ready = any(c.get("type") == "Ready" and c.get("status") == "True" for c in conds)
        pressure = any(c.get("type") in PRESSURE and c.get("status") == "True" for c in conds)
        if (n.get("spec") or {}).get("unschedulable") or not ready or pressure:
            out.add(n["metadata"]["name"])
    return out


def connect(mode: str = "auto"):
    if mode == "client" or (mode == "auto" and os.environ.get("KUBERNETES_SERVICE_HOST")):
        return Client()
    return Kubectl()
