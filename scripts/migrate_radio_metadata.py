#!/usr/bin/env python3
"""Replace the historical combined ``eirp_dbm`` metadata with physical terms.

The migration is deliberately narrow: it only accepts the project's known
26.3 dBm legacy receiver-power reference. Numerical propagation/link values are
not touched. Unknown legacy values fail closed instead of being guessed.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

from radio_link_budget import RX_POWER_REFERENCE_DBM, metadata


CORRECTION = (
    "Metadata correction 2026-07-13: legacy eirp_dbm combined TX EIRP and RX "
    "antenna gain. It was replaced by explicit terminal terms; numerical path "
    "loss and received-power values are unchanged."
)


def migrate_document(document: dict) -> bool:
    radio = document.get("radio")
    if not isinstance(radio, dict) or "eirp_dbm" not in radio:
        return False
    legacy = float(radio["eirp_dbm"])
    if not math.isclose(legacy, RX_POWER_REFERENCE_DBM, abs_tol=1e-9):
        raise ValueError(
            f"refusing unknown legacy eirp_dbm={legacy}; expected "
            f"receiver-power reference {RX_POWER_REFERENCE_DBM}"
        )
    document["radio"] = metadata()
    document["radio_metadata_correction"] = CORRECTION
    return True


def atomic_write(path: Path, document: dict) -> None:
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(document, handle, separators=(",", ":"))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--check", action="store_true",
                        help="Fail when a legacy field remains; do not write")
    args = parser.parse_args(argv)

    pending = []
    for path in args.paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        changed = migrate_document(document)
        if changed:
            pending.append(str(path))
            if not args.check:
                atomic_write(path, document)
    if args.check and pending:
        raise SystemExit(f"legacy radio metadata remains in: {', '.join(pending)}")
    print(json.dumps({"migrated": [] if args.check else pending, "checked": len(args.paths)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
