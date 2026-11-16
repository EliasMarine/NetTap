#!/usr/bin/env python3
"""Fail a release whose tag doesn't match the daemon's NETTAP_VERSION.

    python3 scripts/check_release_version.py v0.4.0-alpha.2 [daemon/services/version_manager.py]

Reads the active top-level assignment with ast, so an old value kept in an OLD CODE comment
can't pass for it. The update check compares that constant with GitHub's releases.
"""

import ast
import os
import sys

DEFAULT_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "daemon",
    "services",
    "version_manager.py",
)


def nettap_version(source: str) -> str | None:
    """The string NETTAP_VERSION is set to at the top level of source, or None."""
    found = None
    for node in ast.parse(source).body:
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "NETTAP_VERSION" for t in node.targets)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            found = node.value.value
    return found


def check(tag: str, path: str = DEFAULT_FILE) -> str | None:
    """None when the tag matches, else what to fix."""
    with open(path) as fh:
        version = nettap_version(fh.read())
    want = tag.removeprefix("v")
    if version == want:
        return None
    return (
        f"NETTAP_VERSION is {version!r}, the tag is {want!r}: set it in "
        "daemon/services/version_manager.py before tagging"
    )


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    problem = check(*sys.argv[1:])
    if problem:
        print(f"::error::{problem}")
        sys.exit(1)
    print(f"NETTAP_VERSION matches {sys.argv[1]}")
