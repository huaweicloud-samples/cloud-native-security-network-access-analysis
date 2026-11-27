import os, sys, tempfile, shutil, zipfile, traceback

def step(name, fn):
    try:
        fn()
        print(f"[OK]   {name}", flush=True)
    except BaseException as e:
        print(f"[FAIL] {name}: {type(e).__name__}: {e}", flush=True)

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bdir = os.path.join(WS, "infra", "_probe_ws")
os.makedirs(bdir, exist_ok=True)

step("write file in workspace", lambda: open(os.path.join(bdir, "a.txt"), "w").close())
step("write file via ZipFile in workspace", lambda: zipfile.ZipFile(os.path.join(bdir, "z.zip"), "w").close())
step("tempfile.mkdtemp()", lambda: tempfile.mkdtemp())
td = None
try:
    td = tempfile.mkdtemp()
except BaseException as e:
    print("[FAIL] tempfile.mkdtemp captured:", type(e).__name__, e, flush=True)
if td:
    step("write file in TEMP dir", lambda: open(os.path.join(td, "b.txt"), "w").close())
    step("shutil.copy into TEMP", lambda: shutil.copy(os.path.join(bdir, "a.txt"), os.path.join(td, "c.txt")))

# cleanup without delete (just leave; env blocks delete)
print("TEMP dir:", tempfile.gettempdir(), flush=True)
print("DONE", flush=True)
