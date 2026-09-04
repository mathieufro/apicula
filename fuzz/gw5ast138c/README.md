# `fuzz/gw5ast138c/` — GW5AST-138C fuzzing harness

Layout and contract are fixed by `spec-harness.md` §1 (this repo's satellite
spec lives in the pipeline, not in-tree). Module rooting is fixed: everything
runs from `$FL/apicula` and is addressed as `fuzz.gw5ast138c.harness.<module>`;
no harness command depends on cwd, and the design directory is always passed
explicitly via `--design-dir`.

## Running one shape locally

```sh
cd $FL/apicula
export GOWINHOME=/Applications/GowinIDE.app/Contents/Resources/Gowin_EDA
export DYLD_LIBRARY_PATH=$GOWINHOME/IDE/lib
export DYLD_FRAMEWORK_PATH=$GOWINHOME/IDE/lib
vendor/venv/bin/python -m fuzz.gw5ast138c.harness --design-dir <path> <shape-args>
```

Every module is currently a stub (`P0.T18`); `__main__.py` and the rest are
filled in starting `P0.T19`. See `shapes/README.md` for the shapes directory
convention and `spec-harness.md` for the full contract (Tcl template, evidence
schema, don't-care mask policy).
