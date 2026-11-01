"""Download and clip OSM roads/waterways/buildings/facilities, GEM active
faults, and GLiM lithology for southern Thailand.

Run with python scripts/download_external_data.py.
Outputs include GeoJSON and zipped shapefiles for Earth Engine table upload.

Buildings and facilities (hospitals, schools, emergency services, transport
hubs, places of worship) are exported AOI-only (no 20 km buffer): unlike
roads/rivers, which need the buffer for distance-factor sampling right at the
AOI edge, these are for overlaying against the susceptibility/rainfall-impact
outputs, which only cover the AOI itself.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile

import geopandas as gpd
import pandas as pd
import requests
import shapely

PROJECT_DIR = Path(__file__).resolve().parent.parent
AOI_PATH = PROJECT_DIR / "data" / "boundary" / "southern_thailand.geojson"
OUTPUT_DIR = PROJECT_DIR / "data" / "external"
RAW_DIR = PROJECT_DIR / "data" / "raw" / "external"  # large source downloads, not part of the deliverable
BUFFER_METERS = 20_000
METRIC_CRS = "EPSG:32647"
# Dated OSM snapshot makes reruns reproducible. Update this URL for newer data.
OSM_URL = "https://download.geofabrik.de/asia/thailand-260908-free.shp.zip"
FAULTS_URL = "https://raw.githubusercontent.com/GEMScienceTools/gem-global-active-faults/master/geojson/gem_active_faults.geojson"
# GLiM v1.1 (Hartmann and Moosdorf, 2012); mirrored by the University of Hamburg
# geology department via a Dropbox link, since there is no versioned API source.
LITHOLOGY_URL = "https://www.dropbox.com/s/9vuowtebp9f1iud/LiMW_GIS%202015.gdb.zip?dl=1"
GLIM_CLASS_FILE = Path(__file__).with_name("glim_lithology_classes.json")
GLIM_CODE_TO_VALUE = {entry["code"]: entry["value"]
                      for entry in json.loads(GLIM_CLASS_FILE.read_text())["classes"]}

# Curated subset of OSM fclass values worth tracking as "critical facilities"
# for impact assessment. Excludes high-volume classes not useful at this scale
# (e.g. individual bus_stop points, every convenience_store in gis_osm_pois).
FACILITY_SOURCES = {
    "gis_osm_pois_free_1": [
        "hospital", "clinic", "doctors", "dentist", "pharmacy", "nursing_home",
        "veterinary", "school", "college", "university", "kindergarten",
        "fire_station", "police", "townhall", "community_centre", "courthouse",
        "embassy", "post_office",
    ],
    "gis_osm_pofw_free_1": None,  # every row here is already a place of worship
    "gis_osm_transport_free_1": [
        "railway_station", "railway_halt", "bus_station", "airport",
        "airfield", "ferry_terminal",
    ],
}


def download(url, path):
    metadata_path = path.with_suffix(path.suffix + ".source.json")
    if path.exists() and metadata_path.exists():
        metadata = json.loads(metadata_path.read_text())
        if metadata["url"] == url:
            print(f"Using cached {path.name}", flush=True)
            return metadata
    partial = path.with_suffix(path.suffix + ".part")
    digest = hashlib.sha256()
    count = 0
    report_at = 50 * 1024**2
    with requests.get(url, stream=True, timeout=(30, 120)) as response:
        response.raise_for_status()
        expected = int(response.headers.get("Content-Length", 0))
        with partial.open("wb") as handle:
            for chunk in response.iter_content(1024**2):
                handle.write(chunk)
                digest.update(chunk)
                count += len(chunk)
                if count >= report_at:
                    print(f"{path.name}: {count / 1024**2:.0f} MiB downloaded", flush=True)
                    report_at += 50 * 1024**2
        # requests transparently decompresses HTTP content encodings.
        if expected and not response.headers.get("Content-Encoding") and count != expected:
            raise ValueError(f"Incomplete download: {path.name}")
        metadata = {
            "url": url, "retrieved_utc": datetime.now(timezone.utc).isoformat(),
            "last_modified": response.headers.get("Last-Modified"),
            "bytes": count, "sha256": digest.hexdigest(),
        }
    partial.replace(path)
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Downloaded {path.name}", flush=True)
    return metadata


def clip_to_mask(frame, mask, geom_types):
    # Most features lie wholly inside the AOI. Only intersect boundary-crossing
    # ones with the detailed polygon, avoiding costly intersections for all rows.
    shapely.prepare(mask)
    candidates = frame.iloc[frame.sindex.query(mask)].copy()
    clipped = candidates[shapely.intersects(mask, candidates.geometry.array)].copy()
    inside = shapely.covers(mask, clipped.geometry.array)
    clipped.loc[~inside, "geometry"] = clipped.loc[~inside].geometry.intersection(mask)
    clipped = clipped.explode(index_parts=False).reset_index(drop=True)
    clipped = clipped[clipped.geometry.geom_type.isin(geom_types)].copy()
    clipped = clipped[~clipped.geometry.is_empty].reset_index(drop=True)
    return clipped


def write_shapefile_package(clipped, name):
    clipped.to_file(OUTPUT_DIR / f"{name}.geojson", driver="GeoJSON")
    # Shapefile names are limited to 10 characters; provide the exact mapping.
    mapping = {}
    used = set()
    for column in clipped.columns:
        if column == "geometry":
            continue
        short = column[:10]
        suffix = 1
        while short in used:
            short = column[:7] + str(suffix)
            suffix += 1
        mapping[column] = short
        used.add(short)
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        clipped.rename(columns=mapping).to_file(
            base / f"{name}.shp", driver="ESRI Shapefile", encoding="UTF-8")
        with zipfile.ZipFile(OUTPUT_DIR / f"{name}.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for part in sorted(base.iterdir()):
                archive.write(part, part.name)
    return mapping


def write_layer(frame, mask, name):
    print(f"Clipping {name}...", flush=True)
    clipped = clip_to_mask(frame, mask, ["LineString"])
    if clipped.empty:
        raise ValueError(f"No line features found for {name}")
    if not clipped.geometry.is_valid.all():
        raise ValueError(f"Invalid geometry in {name}")
    mapping = write_shapefile_package(clipped, name)
    result = {
        "features": len(clipped), "crs": "EPSG:4326",
        "bounds": clipped.total_bounds.tolist(), "shapefile_fields": mapping,
        "length_km": float(clipped.to_crs(METRIC_CRS).length.sum() / 1000),
    }
    if "fclass" in clipped:
        result["classes"] = {str(k): int(v) for k, v in clipped.fclass.value_counts().items()}
    print(f"Wrote {name}: {len(clipped):,} line features", flush=True)
    return result


def write_polygon_layer(frame, mask, name):
    print(f"Clipping {name}...", flush=True)
    clipped = clip_to_mask(frame, mask, ["Polygon"])
    if clipped.empty:
        raise ValueError(f"No polygon features found for {name}")
    if not clipped.geometry.is_valid.all():
        raise ValueError(f"Invalid geometry in {name}")
    mapping = write_shapefile_package(clipped, name)
    result = {
        "features": len(clipped), "crs": "EPSG:4326",
        "bounds": clipped.total_bounds.tolist(), "shapefile_fields": mapping,
        "area_km2": float(clipped.to_crs(METRIC_CRS).area.sum() / 1e6),
    }
    if "xx" in clipped:
        result["classes"] = {str(k): int(v) for k, v in clipped.xx.value_counts().items()}
    print(f"Wrote {name}: {len(clipped):,} polygon features", flush=True)
    return result


def write_point_layer(frame, mask, name):
    print(f"Clipping {name}...", flush=True)
    clipped = clip_to_mask(frame, mask, ["Point"])
    if clipped.empty:
        raise ValueError(f"No point features found for {name}")
    mapping = write_shapefile_package(clipped, name)
    result = {
        "features": len(clipped), "crs": "EPSG:4326",
        "bounds": clipped.total_bounds.tolist(), "shapefile_fields": mapping,
    }
    if "fclass" in clipped:
        result["classes"] = {str(k): int(v) for k, v in clipped.fclass.value_counts().items()}
    print(f"Wrote {name}: {len(clipped):,} point features", flush=True)
    return result


def read_lithology(lithology_path, buffer_mask):
    """Bbox-filtered read of the ~1.2M-polygon global GLiM layer.

    The source geodatabase is in an Eckert IV projection, not WGS84; the
    buffer must be reprojected to it before filtering, or the whole global
    layer would need to be scanned.
    """
    source = f"/vsizip/{lithology_path}"
    layer = "GLiM_export"
    native_crs = gpd.read_file(source, layer=layer, rows=0).crs
    bbox = tuple(gpd.GeoSeries([buffer_mask], crs="EPSG:4326").to_crs(native_crs).total_bounds)
    frame = gpd.read_file(source, layer=layer, bbox=bbox, columns=["xx"]).to_crs("EPSG:4326")
    print(f"Read {len(frame):,} candidate lithology features", flush=True)
    unknown = sorted(set(frame["xx"]) - set(GLIM_CODE_TO_VALUE))
    if unknown:
        raise ValueError(f"Unknown GLiM lithology codes: {unknown}")
    frame["litho_code"] = frame["xx"].map(GLIM_CODE_TO_VALUE).astype(int)
    return frame


def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    osm_path = RAW_DIR / OSM_URL.rsplit("/", 1)[1]
    faults_path = RAW_DIR / "gem_active_faults.geojson"
    lithology_path = RAW_DIR / "LiMW_GIS_2015.gdb.zip"
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs = [pool.submit(download, OSM_URL, osm_path),
                pool.submit(download, FAULTS_URL, faults_path),
                pool.submit(download, LITHOLOGY_URL, lithology_path)]
        sources = [job.result() for job in jobs]
    aoi = gpd.read_file(AOI_PATH).to_crs("EPSG:4326")
    aoi.geometry = aoi.geometry.make_valid()
    masks = {
        "aoi": aoi.geometry.union_all(),
        "buffer20km": gpd.GeoSeries(
            [aoi.to_crs(METRIC_CRS).geometry.union_all().buffer(BUFFER_METERS)],
            crs=METRIC_CRS).to_crs("EPSG:4326").iloc[0],
    }
    def read_osm_layer(archive, stem, bbox):
        members = [n for n in archive.namelist() if Path(n).stem == stem]
        with tempfile.TemporaryDirectory() as temporary:
            for member in members:
                # Copy only the selected layer and never trust archive paths.
                target = Path(temporary) / Path(member).name
                target.write_bytes(archive.read(member))
            frame = gpd.read_file(Path(temporary) / f"{stem}.shp", bbox=bbox).to_crs("EPSG:4326")
        print(f"Read {len(frame):,} candidate features from {stem}", flush=True)
        return frame

    layers = {}
    with zipfile.ZipFile(osm_path) as archive:
        for key, stem in [("roads", "gis_osm_roads_free_1"),
                          ("waterways", "gis_osm_waterways_free_1")]:
            layers[key] = read_osm_layer(archive, stem, masks["buffer20km"].bounds)
        # Buildings/facilities are AOI-only (see module docstring), so a
        # tighter bbox prefilter is enough -- meaningfully faster for the
        # ~250 MB nationwide buildings shapefile.
        layers["buildings"] = read_osm_layer(archive, "gis_osm_buildings_a_free_1", masks["aoi"].bounds)
        facility_parts = []
        for stem, allowlist in FACILITY_SOURCES.items():
            part = read_osm_layer(archive, stem, masks["aoi"].bounds)
            if allowlist is not None:
                part = part[part.fclass.isin(allowlist)]
            facility_parts.append(part[["osm_id", "code", "fclass", "name", "geometry"]])
        layers["facilities"] = gpd.GeoDataFrame(
            pd.concat(facility_parts, ignore_index=True), crs="EPSG:4326")
    # Natural flowing-water lines for distance-to-river/stream modelling.
    # Keep the full waterways output separately (also includes canals/drains).
    layers["rivers"] = layers["waterways"][
        layers["waterways"].fclass.isin(["river", "stream"])]
    layers["faults"] = gpd.read_file(faults_path).to_crs("EPSG:4326")
    layers["lithology"] = read_lithology(lithology_path, masks["buffer20km"])
    writers = {key: write_layer for key in
              ("roads", "waterways", "rivers", "faults")}
    writers["lithology"] = write_polygon_layer
    writers["buildings"] = write_polygon_layer
    writers["facilities"] = write_point_layer
    # Default is both extents (used for distance-factor layers); these two
    # are impact-overlay inputs and only need the strict AOI (see docstring).
    layer_extents = {"buildings": ["aoi"], "facilities": ["aoi"]}
    summary = {
        "aoi": str(AOI_PATH.relative_to(PROJECT_DIR)),
        "aoi_sha256": hashlib.sha256(AOI_PATH.read_bytes()).hexdigest(),
        "buffer_m": BUFFER_METERS, "sources": sources, "outputs": {},
        "limitations": [
            "GEM includes mapped active faults, not all geological faults.",
            "OSM source is Thailand-only; buffered outputs omit foreign-country data.",
            "A 20 km buffer does not guarantee a nearest feature exists within 20 km.",
            "OSM roads retain all road-layer classes, including paths and tracks.",
            "Rivers output includes river and stream classes; waterways retains all classes.",
            "Lithology uses only GLiM's level-1 code (xx); the finer level-2/3 "
            "sub-lithology codes in Litho are not exported.",
            "Buildings/facilities are OSM-mapped only; coverage is incomplete in "
            "rural/remote areas and is not a substitute for a census of structures.",
            "Facilities keep a curated fclass allowlist (hospitals, schools, "
            "emergency services, government offices, transport hubs, places of "
            "worship) -- see FACILITY_SOURCES; it omits e.g. individual bus stops.",
        ],
    }
    for key, frame in layers.items():
        for extent in layer_extents.get(key, ["aoi", "buffer20km"]):
            name = f"{key}_{extent}"
            summary["outputs"][name] = writers[key](frame, masks[extent], name)
    (OUTPUT_DIR / "manifest.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
