#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract_roms2gdp.py

Extract model currents at ~10 m depth from *postprocessed* ROMS 3D files and
collocate them to GDP drifter positions/time.

This replaces the previous workflow that read ROMS history files directly.
Now it reads the IOAPI-style postprocessed files produced by
`post_roms3d_xesmf.py` (see `slurm_run_post_roms3d.bash` for the path pattern).

Expected postprocessed file layout (from slurm_run_post_roms3d.bash):

  POST_ROOT/fYYYYMMDD/inacawo_hindcast_ocean3d_YYYY-mm-dd_HH:MM:SS.nc

Variables used from postprocessed files:
  - Uearth_RHO (TSTEP, LAY, ROW, COL)
  - Vearth_RHO (TSTEP, LAY, ROW, COL)
  - optional TEMP (TSTEP, LAY, ROW, COL)

Depth selection:
  - default is LAY ~= -10 (≈10 m). We pick the closest available LAY value.

Notes on speed:
  - This script indexes model files once, then for each drifter it groups
    observations by matched model file so each model file is opened only once.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr


def nearest_index_1d(sorted_1d: np.ndarray, values: np.ndarray) -> np.ndarray:
    """Vectorized nearest index in a monotonically increasing 1D array."""
    a = np.asarray(sorted_1d)
    v = np.asarray(values)
    idx = np.searchsorted(a, v, side="left")
    idx = np.clip(idx, 1, len(a) - 1)
    left = a[idx - 1]
    right = a[idx]
    choose_left = (v - left) <= (right - v)
    return np.where(choose_left, idx - 1, idx)


def parse_time_from_post_filename(path: Path) -> pd.Timestamp | None:
    """Parse YYYY-mm-dd_HH:MM:SS from postprocessed filename."""
    m = re.search(
        r"inacawo_hindcast_ocean3d_(\d{4}-\d{2}-\d{2})_(\d{2}:\d{2}:\d{2})\.nc$",
        path.name,
    )
    if not m:
        return None
    # Slurm script writes filenames in UTC-like timestamps; treat as UTC
    return pd.to_datetime(f"{m.group(1)} {m.group(2)}", utc=True)


# Depth (m, negative downward). Use -10 for ~10 m.
TARGET_Z = -10.0

# If model longitude is 0..360 and drifter lon is -180..180, convert obs lon.
CONVERT_LON_TO_360_IF_NEEDED = True

# Time matching tolerance between drifter obs times and model file times.
# Increase if your postprocessed files are less frequent.
TIME_TOL = pd.Timedelta("12H")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract postprocessed ROMS currents at GDP drifter positions."
    )
    parser.add_argument("--start", required=True, help="First simulation day (YYYYMMDD)")
    parser.add_argument("--end", required=True, help="Last simulation day (YYYYMMDD)")
    parser.add_argument("--post-root", required=True, type=Path, help="Postprocessed ocean3d directory")
    parser.add_argument("--gdp-file", required=True, type=Path, help="GDP drifter NetCDF file")
    parser.add_argument("--out-dir", required=True, type=Path, help="Directory for extracted drifter files")
    args = parser.parse_args()

    start_ts = pd.to_datetime(args.start, format="%Y%m%d", utc=True)
    end_ts = pd.to_datetime(args.end, format="%Y%m%d", utc=True)
    if start_ts > end_ts:
        parser.error("--start must be on or before --end")
    end_exclusive = end_ts + pd.Timedelta(days=1)

    args.out_dir.mkdir(parents=True, exist_ok=True)

    ds_gdp = xr.open_dataset(args.gdp_file)
    gdp_time_all = pd.to_datetime(ds_gdp["time"].values, utc=True)
    in_range = (gdp_time_all >= start_ts) & (gdp_time_all < end_exclusive)
    ds_gdp = ds_gdp.isel(row=np.flatnonzero(in_range))
    if ds_gdp.sizes.get("row", 0) == 0:
        raise ValueError(
            f"No GDP observations found in {args.gdp_file} for {args.start}..{args.end}."
        )

    # -----------------------------------------------------------------
    # Index postprocessed files once (time -> filepath)
    # -----------------------------------------------------------------
    post_files = sorted(args.post_root.rglob("f*/inacawo_hindcast_ocean3d_*.nc"))
    times: list[pd.Timestamp] = []
    paths: list[str] = []

    for p in post_files:
        t = parse_time_from_post_filename(p)
        if t is None:
            continue
        if start_ts <= t < end_exclusive:
            times.append(t)
            paths.append(str(p))

    if not times:
        raise FileNotFoundError(
            f"No postprocessed files found under {args.post_root} for {args.start}..{args.end}. "
            "Check POST_ROOT and the filename pattern."
        )

    model_index = (
        pd.DataFrame({"time": pd.to_datetime(times), "path": paths})
        .sort_values("time")
        .reset_index(drop=True)
    )

    # Open one file to get the target grid (lat/lon 1D) and available LAY levels
    sample = xr.open_dataset(model_index.loc[0, "path"])
    model_lon = sample["lon"].values.astype(float)
    model_lat = sample["lat"].values.astype(float)
    model_lay = sample["LAY"].values.astype(float)

    lay_idx = int(np.argmin(np.abs(model_lay - TARGET_Z)))
    lay_val = float(model_lay[lay_idx])
    print(f"Using LAY index {lay_idx} (depth={lay_val} m) for TARGET_Z={TARGET_Z} m")
    sample.close()

    # -----------------------------------------------------------------
    # Loop through all unique drifter IDs
    # -----------------------------------------------------------------
    ID = ds_gdp.ID.values
    IDu = np.unique(ID)

    for drifter_id in IDu:
        id_current = np.where(ID == drifter_id)[0]
        ds_gdp_current = ds_gdp.isel(row=id_current)

        # Normalize drifter times to UTC
        gdp_time = pd.to_datetime(ds_gdp_current["time"].values)
        if getattr(gdp_time, "tz", None) is None:
            gdp_time = gdp_time.tz_localize("UTC")
        else:
            gdp_time = gdp_time.tz_convert("UTC")

        # Create new variables in GDP dataset
        ds_gdp_current["u_roms"] = xr.full_like(ds_gdp_current.ve, np.nan)
        ds_gdp_current["v_roms"] = xr.full_like(ds_gdp_current.vn, np.nan)

        # Optional temperature at 10 m, if you want it
        if "sst" in ds_gdp_current:
            ds_gdp_current["temp10m_roms"] = xr.full_like(ds_gdp_current.sst, np.nan)

        print(f"Drifter {drifter_id}: {len(id_current)} obs")

        # Convert lon if needed
        obs_lon = ds_gdp_current["longitude"].values.astype(float)
        if CONVERT_LON_TO_360_IF_NEEDED and (np.nanmax(model_lon) > 180) and (np.nanmin(obs_lon) < 0):
            obs_lon = (obs_lon + 360.0) % 360.0
        obs_lat = ds_gdp_current["latitude"].values.astype(float)

        # Match each drifter time to nearest model time, then group by model file
        obs_df = pd.DataFrame({"itime": np.arange(gdp_time.size), "time": gdp_time}).sort_values("time")

        merged = pd.merge_asof(
            obs_df,
            model_index,
            on="time",
            direction="nearest",
            tolerance=TIME_TOL,
        )

        if merged["path"].isna().any():
            nmiss = int(merged["path"].isna().sum())
            print(f"  [WARN] {nmiss} obs times had no model match within {TIME_TOL}")
            merged = merged.dropna(subset=["path"])

        # Process each matched model file once
        for path, sub in merged.groupby("path"):
            ds_mod = xr.open_dataset(path)

            ii = sub["itime"].values.astype(int)
            lon_idx = nearest_index_1d(model_lon, obs_lon[ii]).astype(int)
            lat_idx = nearest_index_1d(model_lat, obs_lat[ii]).astype(int)

            # Use xarray advanced indexing (vectorized)
            row_idx = xr.DataArray(lat_idx, dims="n")
            col_idx = xr.DataArray(lon_idx, dims="n")

            u = ds_mod["Uearth_RHO"].isel(TSTEP=0, LAY=lay_idx, ROW=row_idx, COL=col_idx).values
            v = ds_mod["Vearth_RHO"].isel(TSTEP=0, LAY=lay_idx, ROW=row_idx, COL=col_idx).values

            ds_gdp_current["u_roms"].values[ii] = u
            ds_gdp_current["v_roms"].values[ii] = v

            if "temp10m_roms" in ds_gdp_current and "TEMP" in ds_mod:
                tt = ds_mod["TEMP"].isel(TSTEP=0, LAY=lay_idx, ROW=row_idx, COL=col_idx).values
                ds_gdp_current["temp10m_roms"].values[ii] = tt

            ds_mod.close()

        out_path = args.out_dir / f"gdp_roms_uv10m_{drifter_id}.nc"
        ds_gdp_current.to_netcdf(out_path)
        print(f"  Wrote {out_path}")


if __name__ == "__main__":
    main()
