"""Create a fresh demo: participants, approved profiles, bands, tokens and config files.

    # simulated bands (no hardware), the default
    .venv/bin/python demo/seed.py --fresh

    # real bands: give the numbers of the bands you own, nothing is guessed
    .venv/bin/python demo/seed.py --fresh --mode real --band alice=36 --band bob=52

Writes (all git-ignored): config/demo.local.json (server), config/hub-<name>.local.json
(one per hub), config/tokens.local.json (phone and operator links). Tokens are printed once.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import config as config_mod          # noqa: E402
from server.db import Database                   # noqa: E402
from server.enroll import PEOPLE, enroll, operator_token   # noqa: E402

SIM_NUMBERS = {"alice": 901, "bob": 902, "cara": 903, "dan": 904}   # simulated bands only


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=config_mod.DEMO_MODES, default="simulated")
    ap.add_argument("--band", action="append", default=[], metavar="NAME=NUMBER",
                    help="band you own, e.g. alice=36 (required for real and single_laptop modes)")
    ap.add_argument("--people", nargs="+", default=["alice", "bob"], choices=sorted(PEOPLE))
    ap.add_argument("--host", default="127.0.0.1", help="address the server binds to")
    ap.add_argument("--public-url", default=None, help="URL hubs and phones use (LAN URL for two laptops)")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--scorer", choices=["deterministic", "claude"], default="deterministic")
    ap.add_argument("--open", action="store_true", help="start everyone open to dating (default: paused)")
    ap.add_argument("--fresh", action="store_true", help="delete the existing demo database first")
    args = ap.parse_args()

    bands = dict(SIM_NUMBERS) if args.mode == "simulated" else {}
    for item in args.band:
        name, _, number = item.partition("=")
        bands[name.strip().lower()] = int(number)
    missing = [p for p in args.people if p not in bands]
    if missing:
        ap.error(f"{args.mode} mode needs the real band number for: {', '.join(missing)} "
                 f"(e.g. --band {missing[0]}=36). Numbers are never guessed.")

    db_path = ROOT / "server" / "vexo.db"
    if args.fresh:
        for suffix in ("", "-wal", "-shm"):
            Path(str(db_path) + suffix).unlink(missing_ok=True)
    elif db_path.exists():
        ap.error("server/vexo.db exists; pass --fresh to start a new demo")

    public = args.public_url or f"http://{args.host}:{args.port}"
    roster = sorted(bands[p] for p in args.people)
    cfg_dir = ROOT / "config"
    cfg_dir.mkdir(exist_ok=True)
    server_cfg = {"host": args.host, "port": args.port, "demo_mode": args.mode, "db_path": str(db_path),
                  "roster": roster, "scorer": {"provider": args.scorer}}
    (cfg_dir / "demo.local.json").write_text(json.dumps(server_cfg, indent=2) + "\n")

    db = Database(str(db_path))
    tokens = {"operator": operator_token(db), "people": {}}
    for person in args.people:
        spec = {k: v for k, v in PEOPLE[person].items()}
        made = enroll(db, band_number=bands[person], open_now=args.open, **spec)
        hub_cfg = {"server_url": public, "hub_token": made["hub_token"], "band_number": bands[person],
                   "roster": roster, "adapter": "sim" if args.mode == "simulated" else "real",
                   "scan": args.mode != "simulated"}
        (cfg_dir / f"hub-{person}.local.json").write_text(json.dumps(hub_cfg, indent=2) + "\n")
        tokens["people"][person] = {"band": bands[person], "user_token": made["user_token"],
                                    "phone_url": f"{public}/?token={made['user_token']}"}
    (cfg_dir / "tokens.local.json").write_text(json.dumps(tokens, indent=2) + "\n")

    print(f"Demo seeded: mode={args.mode}, scorer={args.scorer}, roster={roster}")
    for person, t in tokens["people"].items():
        print(f"  {person:6} band {t['band']:>3}  phone: {t['phone_url']}")
    print(f"  operator: {public}/operator?token={tokens['operator']}")
    print("Configs written to config/*.local.json (git-ignored).")


if __name__ == "__main__":
    main()
