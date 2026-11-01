#!/usr/bin/env python3
"""Combines per-country results into manifest.json."""
import datetime, glob, json, os, sys

out = sys.argv[1] if len(sys.argv) > 1 else "out"
base = "https://github.com/z15981-Wesley/VelaDrive-data/releases/download/packs/"
version = datetime.date.today().strftime("%Y%m%d")
order = ["tw", "cn", "us"]
countries = [json.load(open(p, encoding="utf-8")) for p in glob.glob(os.path.join(out, "*.json")) if not p.endswith("manifest.json")]
countries.sort(key=lambda c: order.index(c["id"]) if c["id"] in order else 99)
for c in countries:
    for r in c["regions"]:
        r["url"] = base + r["file"]
        r["version"] = version
manifest = {
    "format": 1,
    "version": version,
    "generated": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    "attribution": "© OpenStreetMap contributors",
    "license": "ODbL 1.0 — https://opendatacommons.org/licenses/odbl/",
    "countries": countries,
}
json.dump(manifest, open(os.path.join(out, "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(sum(len(c["regions"]) for c in countries), "packs")
