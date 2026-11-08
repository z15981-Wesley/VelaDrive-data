#!/usr/bin/env python3
"""Merge Taiwan speed-camera open data into one CSV in the National Police Agency format.

Base: 內政部警政署「測速執法設置點」(data.gov.tw 7320).
Added: city police / transport department lists that the national list misses —
speed-enforcing technology cameras (科技執法 with 超速/測速) and average-speed sections (區間測速).
Red-light-only, pedestrian, parking and lane cameras are left out: the app warns about speed.

Output columns match the national file so the app reads it unchanged, plus:
  Source        which dataset the row came from
  ZoneLengthM   length of an average-speed section in metres, when published

Usage: tw_merge.py OUT.csv   (downloads everything itself; a source that fails is skipped)
"""
import csv, io, json, math, re, subprocess, sys

UA = "Mozilla/5.0 (VelaDrive data mirror; https://github.com/z15981-Wesley/VelaDrive-data)"
NPA = ("https://opdadm.moi.gov.tw/api/v1/no-auth/resource/api/dataset/EA5E6FCD-B82D-43B7-A5CF-E9893253187E/"
       "resource/7AF37045-DAB0-43D8-A8D4-F0A9691C0B1A/download")
COLS = ["CityName", "RegionName", "Address", "DeptNm", "BranchNm", "Longitude", "Latitude", "direct", "limit",
        "Source", "ZoneLengthM"]


def fetch(url, timeout=90):
    r = subprocess.run(["curl", "-fsSL", "-A", UA, "--retry", "1", "--connect-timeout", "20", "-m", str(timeout), url], capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"curl {r.returncode}")
    return r.stdout


def text(b):
    for enc in ("utf-8-sig", "cp950", "big5"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            pass
    raise RuntimeError("encoding")


def rows(b):
    return list(csv.DictReader(io.StringIO(text(b))))


def num(s):
    try:
        v = float(str(s).strip())
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def latlon(a, b):
    """Two numbers in either order -> (lat, lon) inside Taiwan, or None."""
    a, b = num(a), num(b)
    if a is None or b is None:
        return None
    for lat, lon in ((a, b), (b, a)):
        if 21.5 < lat < 26.5 and 118 < lon < 122.5:
            return lat, lon
    return None


def limit_of(s):
    m = re.search(r"(\d{2,3})", str(s or ""))
    return m.group(1) if m else ""


def length_m(s):
    s = str(s or "").replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*公尺", s)
    if m:
        return str(round(float(m.group(1))))
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:公里|km|KM)", s)
    return str(round(float(m.group(1)) * 1000)) if m else ""


def span_m(s):
    """'台61線177至168.1公里' / '金門大橋5K至0.5K' -> section length in metres."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:[Kk]|公里)?\s*至\s*(\d+(?:\.\d+)?)\s*(?:[Kk]|公里)", str(s or ""))
    if not m:
        return ""
    d = abs(float(m.group(2)) - float(m.group(1)))
    return str(round(d * 1000)) if 0.1 < d < 60 else ""


def row(city, address, lat, lon, direct, limit, source, dept="", branch="", region="", zone_len=""):
    return {"CityName": city, "RegionName": region, "Address": address, "DeptNm": dept, "BranchNm": branch,
            "Longitude": f"{lon:.6f}", "Latitude": f"{lat:.6f}", "direct": direct, "limit": limit,
            "Source": source, "ZoneLengthM": zone_len}


# ---- sources -------------------------------------------------------------------------------------

def taipei():
    url = ("https://data.taipei/api/dataset/745b8808-061f-4f5b-9a62-da1590c049a9/resource/"
           "5012e8ba-5ace-4821-8482-ee07c147fd0a/download")
    out = []
    for r in rows(fetch(url)):
        kind = r.get("功能", "")
        if "測速" not in kind and "區間" not in kind:
            continue
        p = latlon(r.get("緯度"), r.get("經度"))
        if not p:
            continue
        direct = r.get("拍攝方向", "").strip()
        if "區間" in kind and "區間" not in direct:
            direct += "(區間測速)"
        addr = (r.get("設置路段", "") + " " + r.get("設置地點", "")).strip()
        out.append(row("臺北市", addr, *p, direct, limit_of(r.get("速限-速度限制")), "taipei",
                       dept="臺北市政府警察局", region=r.get("轄區", "")))
    return out


def taoyuan():
    url = ("https://opendata.tycg.gov.tw/api/dataset/46bd8de0-cb90-4149-a530-5f5b1751b450/resource/"
           "636bb62e-cc5b-4ad4-ac11-5849ad5c432d/download")
    out = []
    for r in rows(fetch(url)):
        what = r.get("取締項目", "") + r.get("科技執法種類", "")
        if not re.search(r"超速|測速|區間", what):
            continue
        p = latlon(r.get("座標緯度"), r.get("座標經度"))
        if not p:
            continue
        direct = r.get("拍攝方向", "").strip()
        if "區間" in what and "區間" not in direct:
            direct += "(區間測速)"
        addr = r.get("設置地點_路口或路段", "") or r.get("設置區域描述", "")
        out.append(row("桃園市", addr, *p, direct, limit_of(r.get("速限")), "taoyuan",
                       dept="桃園市政府警察局", branch=r.get("管轄單位", ""), region=r.get("行政區", "")))
    return out


def taichung():
    url = "https://newdatacenter.taichung.gov.tw/api/v1/no-auth/resource.download?rid=b3f58c63-53b3-4c01-8203-2a7afa08bb13"
    out = []
    for r in rows(fetch(url)):
        kind = r.get("科技執法種類", "")
        what = kind + r.get("取締項目", "")
        if not re.search(r"超速|測速|區間", what):
            continue
        p = latlon(r.get("緯度"), r.get("經度"))
        if not p:
            continue  # sections published without coordinates
        place = r.get("設置地點", "")
        direct = "雙向"
        m = re.search(r"\(([東西南北]向[東西南北])\)", place)
        if m:
            direct = m.group(1)
        if "區間" in kind:
            direct += "(區間測速)"
        out.append(row("臺中市", place, *p, direct, limit_of(re.search(r"速限\s*(\d+)", r.get("取締項目", "")).group(1)
                                                         if re.search(r"速限\s*(\d+)", r.get("取締項目", "")) else ""),
                       "taichung", dept="臺中市政府警察局", zone_len=length_m(r.get("取締項目")) if "區間" in kind else ""))
    return out


def changhua():
    base = "https://www.chpb.gov.tw/opendata/{}/csv"
    out = []
    for key, zones in (("2XvPDK8t9UC1v65F7FQ4Kw", False), ("deJgXKJjLESCdBNje_-bYA", False),
                       ("iIqaLCWmEU-cNkBdBB-CAQ", True)):
        for r in rows(fetch(base.format(key))):
            what = r.get("取締項目", "") + r.get("科技執法種類", "")
            if not re.search(r"超速|測速|區間", what):
                continue
            p = latlon(r.get("座標緯度"), r.get("座標經度"))
            if not p:
                continue
            place = r.get("設置地點", "").strip()
            zone = zones or "區間" in what
            direct = r.get("拍攝方向", "").strip() or "雙向"
            if zone:
                direct += "(區間測速)"
            out.append(row("彰化縣", place, *p, direct, limit_of(r.get("速限")), "changhua",
                           dept="彰化縣警察局", branch=r.get("管轄分局", "") or r.get("轄區分局", ""),
                           region=r.get("行政區", ""), zone_len=span_m(place) if zone else ""))
    return out


def kinmen():
    url = "https://ws.kinmen.gov.tw/001/Upload/0/relfile/0/0/5ad94bbb-f590-4e3e-b779-5c3ac8a2135f.csv"
    out = []
    for r in rows(fetch(url)):
        p = latlon(r.get("座標緯度"), r.get("座標經度"))  # published lon/lat swapped
        if not p:
            continue
        place = r.get("設置地點", "").strip()
        m = re.search(r"\(([東西南北])向\)", place)
        opposite = {"東": "西", "西": "東", "南": "北", "北": "南"}
        direct = f"{opposite[m.group(1)]}向{m.group(1)}" if m else "雙向"
        out.append(row("金門縣", place, *p, direct + "(區間測速)", limit_of(r.get("速限長度") or r.get("速限")),
                       "kinmen", dept="金門縣警察局", branch=r.get("管轄分局", ""), region=r.get("行政區", ""),
                       zone_len=span_m(place)))
    return out


# Not added (checked 2026-11): Hualien publishes sections by mileage only, no coordinates; Kaohsiung,
# Hsinchu County, Chiayi County and Pingtung portals don't answer outside Taiwan (GitHub runners).
SOURCES = [taipei, taoyuan, taichung, changhua, kinmen]


# ---- merge ---------------------------------------------------------------------------------------

def dist(a, b):
    lat = math.radians((a[0] + b[0]) / 2)
    return math.hypot((a[0] - b[0]) * 111_320, (a[1] - b[1]) * 111_320 * math.cos(lat))


def main(out_path):
    base = rows(fetch(NPA, 180))
    base = [r for r in base if num(r.get("Latitude")) and num(r.get("Longitude"))]
    if len(base) < 1000:
        sys.exit(f"national list too short: {len(base)}")
    merged = [dict(r, Source="npa", ZoneLengthM="") for r in base]
    points = [(float(r["Latitude"]), float(r["Longitude"]), "區間" in r.get("direct", "")) for r in merged]
    report = [f"npa: {len(base)}"]
    for src in SOURCES:
        try:
            got = src()
        except Exception as e:  # one city being down must not stop the weekly update
            report.append(f"{src.__name__}: FAILED ({e})")
            continue
        added = 0
        for r in got:
            p = (float(r["Latitude"]), float(r["Longitude"]))
            zone = "區間" in r["direct"]
            # Same place already listed (national data, or an earlier city row): keep the first.
            if any(z == zone and dist(p, q[:2]) < 60 for q in points for z in [q[2]]):
                continue
            merged.append(r)
            points.append((*p, zone))
            added += 1
        report.append(f"{src.__name__}: {len(got)} speed rows, {added} new")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(merged)
    zones = sum("區間" in r.get("direct", "") for r in merged)
    report.append(f"zones: {zones}")
    print("\n".join(report))
    if len(sys.argv) > 2:
        with open(sys.argv[2], "w", encoding="utf-8") as f:
            f.write("\n".join(report) + f"\ntotal: {len(merged)}\n")
    print(f"total: {len(merged)}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "tw_speed_cameras.csv")
