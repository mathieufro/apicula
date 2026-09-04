"""Test-design generator: RTL + .cst + .sdc from a shape spec.

Stub created by P0.T18 (`spec-harness.md` §1). Implementation lands in P0.T20.
Module rooting is fixed: this module is always addressed as
`fuzz.gw5ast138c.harness.gen` and run from `$FL/apicula`; it never depends
on cwd -- the design directory is always passed explicitly via `--design-dir`.
"""
import argparse


def build_parser():
    """Return this module's argparse parser.

    Every harness module parser carries a required `--design-dir` so no
    harness command depends on the current working directory
    (`spec-harness.md` §1, `spec.md` V5/V6).
    """
    parser = argparse.ArgumentParser(prog="fuzz.gw5ast138c.harness.gen")
    parser.add_argument(
        "--design-dir",
        required=True,
        help="Directory holding the test design for this run (never inferred from cwd).",
    )
    return parser


def main(argv=None):
    """Stub entry point. Implemented by P0.T20."""
    raise NotImplementedError(
        "fuzz.gw5ast138c.harness.gen.main is a P0.T18 stub; implemented by P0.T20"
    )


if __name__ == "__main__":
    main()
