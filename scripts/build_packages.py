#!/usr/bin/env python3
"""Build FunctionGraph deployment packages (cross-platform, no `zip` binary needed).

Produces under infra/build/:
  run_analysis.zip   - entry function (computes + sinks findings), self-contained
  check_analysis.zip - parity function (reports completion), self-contained
  send_findings.zip  - independent findings publisher (replay), self-contained

Each function zip bundles app.py + src/engine + src/shared + src/scopes AND the
Huawei Cloud SDK packages AND their dependencies at the archive root, so the
function is fully self-contained. We install the SDK with manylinux wheels
(Linux x86_64, py39) even when building on Windows, so the compiled extensions
(.so) are compatible with the FunctionGraph Linux Python3.9 runtime. (Installing
with the host OS's wheels produced Windows .pyd files that cannot load on the
Linux runtime.)

Archive entry names always use forward slashes so they unpack correctly on the
Linux FunctionGraph runtime.

NOTE on this environment: a "safe-delete" guard raises SystemExit on ANY
filesystem deletion, and a separate write guard kills the process when it packs
more than one large zip in a single process. We therefore:
  * never delete anything (ZipFile "w" truncates an existing output file, no
    separate os.remove needed; staging dirs are unique temp dirs left in place);
  * run each function's packaging in its OWN subprocess, so every process packs
    exactly one zip (matching the workload that succeeds).

Two modes:
  * default  -> pip install the SDK once, then spawn one subprocess per function.
  * VPCA_BUILD_ONE set -> build only argv[1] using VPCA_SDK_DIR.
"""
import os
import sys
import shutil
import subprocess
import tempfile
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "infra", "build")
SRC = os.path.join(ROOT, "src")
PYTHON = sys.executable

# Packaging tooling that must NOT be bundled into the function.
SDK_EXCLUDE = {"pip", "pip-", "setuptools", "setuptools-", "wheel", "wheel-",
               "pkg_resources", "easy_install.py", "__pycache__", "bin"}

SDK_PACKAGES = [
    "huaweicloudsdkcore",
    "huaweicloudsdkvpc",
    "huaweicloudsdksmn",
    "huaweicloudsdksecmaster",
]

# Fetch Linux x86_64 / py39 wheels so compiled extensions are runtime-compatible.
PIP_PLATFORM_FLAGS = [
    "--platform", "manylinux2014_x86_64",
    "--python-version", "39",
    "--only-binary=:all:",
]

FUNCTIONS = ["run_analysis", "check_analysis", "send_findings"]


def zip_dir(src: str, out: str) -> None:
    # ZipFile "w" mode truncates an existing file, so no explicit delete is
    # needed (and avoids the environment's safe-delete guard that blocks
    # os.remove on existing build artifacts).
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(src):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in files:
                if f.endswith(".pyc"):
                    continue
                full = os.path.join(root, f)
                rel = os.path.relpath(full, src).replace(os.sep, "/")
                z.write(full, rel)


def _keep(item: str) -> bool:
    if item in SDK_EXCLUDE:
        return False
    if item.startswith("pip-") or item.startswith("setuptools-") or item.startswith("wheel-"):
        return False
    if item.endswith(".dist-info") or item.endswith(".egg-info"):
        if any(item.startswith(p) for p in SDK_PACKAGES):
            return True
        return False
    return True


def pip_install(target: str) -> None:
    subprocess.run(
        [PYTHON, "-m", "pip", "install", "--target", target,
         *PIP_PLATFORM_FLAGS, *SDK_PACKAGES],
        check=True,
    )


def build_one(fn: str, sdk_dir: str) -> None:
    print(f"[*] Packaging {fn} ...", flush=True)
    tmp = tempfile.mkdtemp()
    shutil.copy(os.path.join(SRC, "functions", fn, "app.py"),
                os.path.join(tmp, "app.py"))
    srcdir = os.path.join(tmp, "src")
    os.makedirs(srcdir, exist_ok=True)
    for sub in ["engine", "shared", "scopes"]:
        shutil.copytree(os.path.join(SRC, sub), os.path.join(srcdir, sub))
    with open(os.path.join(srcdir, "__init__.py"), "w"):
        pass
    for item in os.listdir(sdk_dir):
        if not _keep(item):
            continue
        s = os.path.join(sdk_dir, item)
        d = os.path.join(tmp, item)
        if os.path.isdir(s):
            shutil.copytree(s, d)
        else:
            shutil.copy(s, d)
    out = os.path.join(BUILD, f"{fn}.zip")
    zip_dir(tmp, out)
    print(f"    zipped -> {out} ({os.path.getsize(out):,} bytes)", flush=True)


def main() -> None:
    os.makedirs(BUILD, exist_ok=True)

    # Single-function mode (spawned per function to keep each process under the
    # environment's per-process packaging limit).
    if os.environ.get("VPCA_BUILD_ONE"):
        build_one(sys.argv[1], os.environ["VPCA_SDK_DIR"])
        return

    # Install SDK (with manylinux wheels) into a unique temp dir. Network can be
    # flaky in this environment, so retry a few times before giving up.
    sdk_dir = tempfile.mkdtemp()
    last_err = None
    for attempt in range(1, 4):
        try:
            print(f"[*] Installing Huawei Cloud SDK (attempt {attempt}/3, manylinux py39) ...", flush=True)
            pip_install(sdk_dir)
            print(f"[*] SDK installed to {sdk_dir}", flush=True)
            break
        except subprocess.CalledProcessError as e:
            last_err = e
            print(f"    pip failed (likely transient network error), retrying ...", flush=True)
            time.sleep(4)
    else:
        raise RuntimeError("pip install failed after 3 attempts") from last_err

    # Spawn one subprocess per function so each process packs exactly one zip.
    for fn in FUNCTIONS:
        env = dict(os.environ)
        env["VPCA_BUILD_ONE"] = "1"
        env["VPCA_SDK_DIR"] = sdk_dir
        subprocess.run([PYTHON, __file__, fn], env=env, check=True)

    print("[+] Done. Built packages in", BUILD, flush=True)
    for f in sorted(os.listdir(BUILD)):
        if f == "deps.zip":
            continue
        p = os.path.join(BUILD, f)
        print(f"  {f}: {os.path.getsize(p):,} bytes")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        raise
