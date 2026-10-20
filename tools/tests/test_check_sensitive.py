"""check_sensitive: built-in patterns plus the untracked private list of site names."""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import check_sensitive  # noqa: E402


def repo_with(tmp_path, text):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "notes.md").write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "notes.md"], check=True)
    return str(tmp_path)


def test_builtin_pattern(tmp_path, monkeypatch):
    monkeypatch.setenv("SENSITIVE_PRIVATE_LIST", str(tmp_path / "missing.txt"))
    internal = ".".join(["10", "1", "2", "3"])  # built at run time so this file stays clean
    repo = repo_with(tmp_path, "endpoint %s, docs use 192.0.2.10\n" % internal)
    assert [f[2] for f in check_sensitive.scan(repo)] == ["internal IPv4"]


def test_private_list(tmp_path, monkeypatch):
    lst = tmp_path / "private.txt"
    lst.write_text("# site node names\nsite-node-a\n/home/alice\n", encoding="utf-8")
    monkeypatch.setenv("SENSITIVE_PRIVATE_LIST", str(lst))
    repo = repo_with(tmp_path / "r", "runs on Site-Node-A\npath /home/alice/x\nnpu-node-1 is fine\n")
    found = check_sensitive.scan(repo)
    assert [(f[1], f[2]) for f in found] == [(1, "private site name"), (2, "private site name")]
