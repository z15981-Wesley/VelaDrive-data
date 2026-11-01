#!/usr/bin/env python3
"""Merges partial results (*.part.json) into manifest.json, keeping packs from the
previous manifest that were not rebuilt in this run."""
import datetime, glob, json, os, sys

out = sys.argv[1] if len(sys.argv) > 1 else "out"
previous_path = sys.argv[2] if len(sys.argv) > 2 else ""
base = "https://github.com/z15981-Wesley/VelaDrive-data/releases/download/packs/"
version = datetime.date.today().strftime("%Y%m%d")
regions_def = json.load(open("regions.json", encoding="utf-8"))
order = [c["id"] for c in regions_def["countries"]]

previous = {}
if previous_path and os.path.exists(previous_path):
    for c in json.load(open(previous_path, encoding="utf-8")).get("countries", []):
        previous[c["id"]] = {r["id"]: r for r in c["regions"]}

built = {}
for path in glob.glob(os.path.join(out, "*.part.json")):
    part = json.load(open(path, encoding="utf-8"))
    for r in part["regions"]:
        r["url"] = base + r["file"]
        r["version"] = version
        built.setdefault(part["id"], {})[r["id"]] = r

countries = []
for c in regions_def["countries"]:
    merged = []
    for rdef in c["regions"]:
        r = built.get(c["id"], {}).get(rdef["id"]) or previous.get(c["id"], {}).get(rdef["id"])
        if r:
            merged.append(r)
    if merged:
        countries.append({"id": c["id"], "name": c["name"], "regions": merged})

manifest = {
    "format": 1,
    "version": version,
    "generated": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    "attribution": "© OpenStreetMap contributors",
    "license": "ODbL 1.0 — https://opendatacommons.org/licenses/odbl/",
    "countries": countries,
}
json.dump(manifest, open(os.path.join(out, "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(sum(len(c["regions"]) for c in countries), "packs in manifest;", sum(len(v) for v in built.values()), "rebuilt")
