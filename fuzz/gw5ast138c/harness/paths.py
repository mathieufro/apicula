"""Every absolute root the harness needs, derived -- never written down.

`S24` ships these modules upstream, so a home-directory literal anywhere in
them is a defect: on any other box the harness, and every test that reaches
for an artefact, simply cannot run.  Each root here is read from the
environment variable the LOOP-BRIEF already names for it, and falls back to a
location derived from this checkout or from `$HOME` -- so the values on the
box this was written on are unchanged, and the code no longer asserts them.

Nothing here creates a directory or fails: a root that does not exist on this
box is a fact for the caller to skip on, with a reason, not an import error.
"""
import os

#: `$DATASTORE` -- the git-ignored binary store (`spec-harness.md` §5).
DATASTORE_ENV = "DATASTORE"
#: `$OTC_EVIDENCE` -- the `open-toolchain` submodule's evidence tree (`C10`).
OTC_EVIDENCE_ENV = "OTC_EVIDENCE"
#: `$GOWIN_UPSTREAM_VENV` -- the `apycula==0.33` baseline venv (`S26`).
UPSTREAM_VENV_ENV = "GOWIN_UPSTREAM_VENV"


def repo_root():
    """The apicula checkout this module belongs to."""
    here = os.path.abspath(__file__)
    for _ in range(4):                       # harness -> gw5ast138c -> fuzz -> repo
        here = os.path.dirname(here)
    return here


def datastore():
    """Root of the binary artefact store; `$DATASTORE` wins."""
    return (os.environ.get(DATASTORE_ENV)
            or os.path.join(os.path.expanduser("~"), "fine-line-data",
                            "open-toolchain-gw5ast"))


def otc_evidence():
    """The evidence tree, a sibling checkout of this one; `$OTC_EVIDENCE` wins."""
    return (os.environ.get(OTC_EVIDENCE_ENV)
            or os.path.join(os.path.dirname(repo_root()), "open-toolchain",
                            "evidence"))


def upstream_venv():
    """The `apycula==0.33` comparison venv, or `None` if this box has none."""
    named = os.environ.get(UPSTREAM_VENV_ENV)
    if named:
        return named
    # `$FL/vendor/venv-upstream`, four levels above a worktree checkout.
    root = repo_root()
    for _ in range(3):                       # apicula -> <slug> -> worktrees -> .atelier
        root = os.path.dirname(root)
    guess = os.path.join(os.path.dirname(root), "vendor", "venv-upstream")
    return guess if os.path.isdir(guess) else None
