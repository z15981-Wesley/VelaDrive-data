# Vela Drive offline data

Offline packs used by the Vela Drive app: posted road speed limits and community speed cameras,
one pack per region (Taiwan; provinces of mainland China; US states). Rebuilt monthly by GitHub Actions
from [Geofabrik](https://download.geofabrik.de/) OpenStreetMap extracts.

Download from the [`packs` release](https://github.com/z15981-Wesley/VelaDrive-data/releases/tag/packs);
`manifest.json` lists every pack with its size and SHA-256.

## License

Map data © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), available under the
[Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/). The packs are a derived
database and are distributed under the same license.

## Format

See `scripts/build_packs.py` for the binary layout (`VDP1`: tile index + raw-DEFLATE tile records).
