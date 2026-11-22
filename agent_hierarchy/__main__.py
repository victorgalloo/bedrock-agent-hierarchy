"""`python -m agent_hierarchy validate <org.yaml>`"""

from __future__ import annotations

import sys

from agent_hierarchy.org import Level, load_org


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2 or args[0] != "validate":
        print("usage: python -m agent_hierarchy validate <org.yaml>", file=sys.stderr)
        return 2
    org = load_org(args[1])
    counts = ", ".join(f"{len(org.names(lv))} {lv.value}" for lv in Level)
    print(f"ok: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
