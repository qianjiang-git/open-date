"""Seed the hosted Postgres demo without touching the local SQLite database.

    DATABASE_URL=postgresql://... .venv/bin/python scripts/seed_hosted.py --fresh \
        --public-url https://vexo-match.onrender.com

The deployed service already runs migrations on startup. This script opens the same
database, optionally resets the schema, enrolls the demo people and writes the phone
and operator links to config/tokens.hosted.local.json (git-ignored).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import config as config_mod          # noqa: E402
from server.enroll import PEOPLE, enroll, operator_token   # noqa: E402
from server.pg import database_url, open_database          # noqa: E402

SIM_NUMBERS = {"alice": 901, "bob": 902, "cara": 903, "dan": 904}
DEFAULT_PUBLIC_URL = "https://vexo-match.onrender.com"


def reset_schema(dsn: str) -> None:
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
        conn.execute("GRANT ALL ON SCHEMA public TO public")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=config_mod.DEMO_MODES, default="simulated")
    ap.add_argument("--band", action="append", default=[], metavar="NAME=NUMBER",
                    help="band you own, e.g. alice=36 (required for real and single_laptop modes)")
    ap.add_argument("--people", nargs="+", default=["alice", "bob"], choices=sorted(PEOPLE))
    ap.add_argument("--public-url", default=DEFAULT_PUBLIC_URL,
                    help=f"URL phones and hubs use (default: {DEFAULT_PUBLIC_URL})")
    ap.add_argument("--open", action="store_true", help="start everyone open to dating (default: paused)")
    ap.add_argument("--fresh", action="store_true", help="drop and recreate the Postgres schema before seeding")
    args = ap.parse_args()

    dsn = database_url()
    if not dsn:
        ap.error("DATABASE_URL must be set to a postgres:// or postgresql:// URL")
    if args.fresh:
        reset_schema(dsn)

    bands = dict(SIM_NUMBERS) if args.mode == "simulated" else {}
    for item in args.band:
        name, _, number = item.partition("=")
        bands[name.strip().lower()] = int(number)
    missing = [p for p in args.people if p not in bands]
    if missing:
        ap.error(f"{args.mode} mode needs the real band number for: {', '.join(missing)} "
                 f"(e.g. --band {missing[0]}=36). Numbers are never guessed.")

    public = args.public_url.rstrip("/")
    roster = sorted(bands[p] for p in args.people)
    cfg_dir = ROOT / "config"
    cfg_dir.mkdir(exist_ok=True)
    db = open_database()

    tokens = {"public_url": public, "mode": args.mode, "operator": operator_token(db), "people": {}}
    try:
        for person in args.people:
            spec = {k: v for k, v in PEOPLE[person].items()}
            made = enroll(db, band_number=bands[person], open_now=args.open, **spec)
            tokens["people"][person] = {
                "band": bands[person],
                "user_token": made["user_token"],
                "hub_token": made["hub_token"],
                "phone_url": f"{public}/?token={made['user_token']}",
            }
            hub_cfg = {
                "server_url": public,
                "hub_token": made["hub_token"],
                "band_number": bands[person],
                "roster": roster,
                "adapter": "sim" if args.mode == "simulated" else "real",
                "scan": args.mode != "simulated",
            }
            (cfg_dir / f"hub-{person}.hosted.local.json").write_text(json.dumps(hub_cfg, indent=2) + "\n")
    finally:
        db.close()

    tokens["operator_url"] = f"{public}/operator?token={tokens['operator']}"
    out = cfg_dir / "tokens.hosted.local.json"
    out.write_text(json.dumps(tokens, indent=2) + "\n")

    print(f"Hosted demo seeded: mode={args.mode}, roster={roster}, public_url={public}")
    for person, t in tokens["people"].items():
        print(f"  {person:6} band {t['band']:>3}")
    print(f"Links written to {out} (git-ignored).")
    print(f"Hub configs written to {cfg_dir}/hub-*.hosted.local.json (git-ignored).")
    example = args.people[0]
    flag = " --sim" if args.mode == "simulated" else ""
    print(f"Run a hub with: .venv/bin/python -m hub.hub --config config/hub-{example}.hosted.local.json{flag}")


if __name__ == "__main__":
    main()
