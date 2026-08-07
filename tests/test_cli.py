"""The launcher, which has to work before anything is installed."""

import os
import subprocess
import sys

import pytest


def run(repo_root, *args, env=None):
    e = dict(os.environ)
    e.pop("PYTHONPATH", None)
    e.update(env or {})
    return subprocess.run([os.path.join(repo_root, "amdgraph"), *args],
                          capture_output=True, text=True, timeout=60, env=e)


def test_help_works_from_a_bare_checkout(repo_root):
    r = run(repo_root, "--help")
    assert r.returncode == 0, r.stderr
    assert "--interval" in r.stdout
    assert "space freeze" in r.stdout          # the key bindings reach --help


def test_help_does_not_need_numpy_or_qt(repo_root, tmp_path):
    """--help must print advice, not a traceback, on a machine missing the
    dependencies -- which is the entire reason __main__ defers the imports.
    Simulated by shadowing both packages with modules that refuse to load."""
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    for name in ("numpy", "PyQt6"):
        (shadow / f"{name}.py").write_text("raise ImportError('shadowed')\n")
    r = run(repo_root, "--help", env={"PYTHONPATH": str(shadow)})
    assert r.returncode == 0, r.stderr + r.stdout
    assert "--interval" in r.stdout


def test_missing_dependencies_give_one_line_of_advice(repo_root, tmp_path):
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    (shadow / "numpy.py").write_text("raise ImportError('shadowed')\n")
    r = run(repo_root, "--interval", "1", env={"PYTHONPATH": str(shadow)})
    assert r.returncode != 0
    assert "numpy" in r.stderr
    assert "Traceback" not in r.stderr


def test_launcher_works_through_a_symlink(repo_root, tmp_path):
    link = tmp_path / "ag"
    link.symlink_to(os.path.join(repo_root, "amdgraph"))
    r = subprocess.run([str(link), "--help"], capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stderr
    assert "--interval" in r.stdout


@pytest.mark.parametrize("tool", ["check-layers.py", "amdgraph-probe"])
def test_tools_are_executable_and_have_help(repo_root, tool):
    path = os.path.join(repo_root, "tools", tool)
    assert os.access(path, os.X_OK), f"{tool} is not executable"
    r = subprocess.run([sys.executable, path, "--help"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
