import py_compile
import sys

files = [
    "agents/resumo_diario/tools/definitions.py",
    "agents/resumo_diario/agent.py",
]

all_ok = True
for f in files:
    try:
        py_compile.compile(f, doraise=True)
        print(f"  OK: {f}")
    except py_compile.PyCompileError as e:
        print(f"  FAIL: {f} -> {e}")
        all_ok = False

if all_ok:
    print("\nAll files passed syntax check.")
else:
    print("\nSome files have syntax errors!")
    sys.exit(1)
