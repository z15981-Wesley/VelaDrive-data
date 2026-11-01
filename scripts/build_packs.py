#!/usr/bin/env python3
"""Builds Vela Drive offline packs from OpenStreetMap extracts.

Input: GeoJSON-sequence files exported by `osmium export` from extracts filtered to
ways with a maxspeed tag and speed-camera nodes.
Output: one pack per region (province / state / country) plus manifest.json.

Pack format (little endian):
  "VDP1"  u32 tileCount
  tileCount x { i16 latKey, i16 lonKey, u32 offset, u32 length }   (key = floor(deg * 4))
  blobs: raw DEFLATE of tile records
Records:
  way:    u8 1, u8 forwardKph, u8 backwardKph, u16 n, n x { i32 lat*1e5, i32 lon*1e5 }
          (0 = no limit / no travel in that direction; forward = point order)
  camera: u8 2, u8 limitKph, u16 heading (0xFFFF none), i32 lat*1e5, i32 lon*1e5, i64 osm id
"""
import argparse, hashlib, json, math, os, re, struct, sys, zlib
from collections import defaultdict

TILE = 4  # tiles per degree


def kph(value):
    if not value:
        return None
    v = value.strip().lower()
    if ";" in v:
        v = v.split(";")[0]
    if "|" in v:  # per-lane limits: take the highest
        vals = [kph(x) for x in v.split("|")]
        vals = [x for x in vals if x]
        return max(vals) if vals else None
    m = re.match(r"^\s*(\d+(?:\.\d+)?)", v)
    if not m:
        return None
    n = float(m.group(1))
    if "mph" in v:
        n *= 1.609344
    n = int(round(n))
    return n if 5 <= n <= 160 else None


COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def heading(value):
    if not value:
        return None
    t = value.strip().upper()
    try:
        return float(t) % 360
    except ValueError:
        pass
    return COMPASS.index(t) * 22.5 if t in COMPASS else None


def tile_key(lat, lon):
    return (math.floor(lat * TILE), math.floor(lon * TILE))


def segment_tiles(a, b):
    """Tiles touched by the bounding box of segment a-b (lat, lon)."""
    la0, lo0 = tile_key(min(a[0], b[0]), min(a[1], b[1]))
    la1, lo1 = tile_key(max(a[0], b[0]), max(a[1], b[1]))
    for la in range(la0, la1 + 1):
        for lo in range(lo0, lo1 + 1):
            yield (la, lo)


ONEWAY_YES = {"yes", "1", "true"}


def way_record(tags, coords):
    """coords: [(lat, lon)]. Returns (record bytes, points) or None."""
    base = kph(tags.get("maxspeed"))
    fwd = kph(tags.get("maxspeed:forward")) or base
    bwd = kph(tags.get("maxspeed:backward")) or base
    if not fwd and not bwd:
        return None
    oneway = tags.get("oneway", "").lower()
    implied = tags.get("highway") in ("motorway",) or tags.get("junction") in ("roundabout", "circular")
    if oneway == "-1":
        coords = coords[::-1]
        fwd, bwd = bwd, 0
    elif oneway in ONEWAY_YES or (implied and oneway != "no"):
        bwd = 0
    if len(coords) < 2 or len(coords) > 65535:
        return None
    rec = struct.pack("<BBBH", 1, fwd or 0, bwd or 0, len(coords))
    rec += b"".join(struct.pack("<ii", round(lat * 1e5), round(lon * 1e5)) for lat, lon in coords)
    return rec, coords


def camera_record(tags, lat, lon, osm_id):
    limit = kph(tags.get("maxspeed")) or 0
    h = heading(tags.get("direction") or tags.get("camera:direction"))
    hv = 0xFFFF if h is None else int(round(h)) % 360
    return struct.pack("<BBHiiq", 2, limit, hv, round(lat * 1e5), round(lon * 1e5), osm_id)


class TileStore:
    """Appends records to per-tile files on disk so memory stays small."""

    def __init__(self, root):
        self.root = root
        os.makedirs(root, exist_ok=True)
        self.buffers = defaultdict(list)
        self.size = 0
        self.counts = defaultdict(lambda: [0, 0])

    def add(self, key, rec, kind):
        self.buffers[key].append(rec)
        self.size += len(rec)
        self.counts[key][kind] += 1
        if self.size > 200_000_000:
            self.flush()

    def flush(self):
        for key, recs in self.buffers.items():
            with open(self.path(key), "ab") as f:
                f.write(b"".join(recs))
        self.buffers.clear()
        self.size = 0

    def path(self, key):
        return os.path.join(self.root, f"{key[0]}_{key[1]}.bin")

    def keys(self):
        for name in os.listdir(self.root):
            a, b = name[:-4].split("_")
            yield (int(a), int(b))


def ingest(store, path):
    ways = cams = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip().lstrip("\x1e")
            if not line:
                continue
            feat = json.loads(line)
            props = feat.get("properties") or {}
            geom = feat.get("geometry") or {}
            osm_id = props.pop("@id", None) or feat.get("id") or 0
            if isinstance(osm_id, str):
                osm_id = int(re.sub(r"\D", "", osm_id) or 0)
            if geom.get("type") == "Point":
                if props.get("highway") != "speed_camera":
                    continue
                lon, lat = geom["coordinates"][:2]
                store.add(tile_key(lat, lon), camera_record(props, lat, lon, osm_id), 1)
                cams += 1
            elif geom.get("type") == "LineString":
                if "highway" not in props:
                    continue  # railways etc. also carry maxspeed
                coords = [(c[1], c[0]) for c in geom["coordinates"]]
                built = way_record(props, coords)
                if not built:
                    continue
                rec, pts = built
                touched = set()
                for i in range(len(pts) - 1):
                    touched.update(segment_tiles(pts[i], pts[i + 1]))
                for key in touched:
                    store.add(key, rec, 0)
                ways += 1
    store.flush()
    return ways, cams


def build_pack(store, bbox, out_path):
    min_lat, min_lon, max_lat, max_lon = bbox
    la0, lo0 = tile_key(min_lat, min_lon)
    la1, lo1 = tile_key(max_lat, max_lon)
    tiles = []
    ways = cams = 0
    for la in range(la0, la1 + 1):
        for lo in range(lo0, lo1 + 1):
            p = store.path((la, lo))
            if not os.path.exists(p):
                continue
            with open(p, "rb") as f:
                raw = f.read()
            c = zlib.compressobj(9, zlib.DEFLATED, -15)
            blob = c.compress(raw) + c.flush()
            tiles.append(((la, lo), blob))
            w, k = store.counts.get((la, lo), (0, 0))
            ways += w
            cams += k
    if not tiles:
        return None
    header = b"VDP1" + struct.pack("<I", len(tiles))
    offset = len(header) + 12 * len(tiles)
    index = b""
    for (la, lo), blob in tiles:
        index += struct.pack("<hhII", la, lo, offset, len(blob))
        offset += len(blob)
    data = header + index + b"".join(b for _, b in tiles)
    with open(out_path, "wb") as f:
        f.write(data)
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "tiles": len(tiles),
            "ways": ways, "cameras": cams}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--country", required=True)
    ap.add_argument("--input", nargs="+", required=True, help="GeoJSON-sequence files")
    ap.add_argument("--regions", required=True, help="regions.json")
    ap.add_argument("--work", default="work")
    ap.add_argument("--out", default="out")
    args = ap.parse_args()

    regions = json.load(open(args.regions, encoding="utf-8"))
    country = next(c for c in regions["countries"] if c["id"] == args.country)
    store = TileStore(os.path.join(args.work, args.country))
    for path in args.input:
        w, k = ingest(store, path)
        print(f"{path}: {w} ways, {k} cameras", file=sys.stderr)
    # Counts are only exact within this run; reload from disk if resumed.
    os.makedirs(args.out, exist_ok=True)
    result = {"id": country["id"], "name": country["name"], "regions": []}
    for region in country["regions"]:
        file = f"{country['id']}-{region['id']}.vdp"
        pad = 0.05
        b = region["bbox"]
        info = build_pack(store, (b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad), os.path.join(args.out, file))
        if not info:
            print(f"  {region['id']}: no data", file=sys.stderr)
            continue
        entry = {"id": region["id"], "name": region["name"], "bbox": region["bbox"], "file": file}
        entry.update(info)
        result["regions"].append(entry)
        print(f"  {region['id']}: {info['bytes'] / 1e6:.1f} MB, {info['ways']} way-tiles, {info['cameras']} cameras", file=sys.stderr)
    json.dump(result, open(os.path.join(args.out, f"{country['id']}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
