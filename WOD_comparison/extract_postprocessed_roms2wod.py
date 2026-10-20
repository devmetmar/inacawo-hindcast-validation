#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Extract postprocessed CAWO ROMS temperature and salinity profiles at WOD CTD
cast locations/times.

The postprocessed ROMS files are expected to contain:
    TEMP(TSTEP, LAY, ROW, COL)
    SALT(TSTEP, LAY, ROW, COL)
    lat(ROW)
    lon(COL)
    LAY(LAY)              # depths in m; 0 at surface, negative downward
    TSTEP(TSTEP)          # CF time coordinate

One output NetCDF file is written per WOD cast, analogous to the original
extract_roms2wod.py workflow.

Use --roms-dir to select the postprocessed ocean3d directory. The supported
run_wod_comparison.bash entrypoint supplies the path from $CAWO_POST. If the
nearest grid cell contains only fill values, the immediate neighboring cells
are checked and the nearest valid ROMS profile is selected.
"""

from pathlib import Path
import argparse
import re
import numpy as np
import pandas as pd
import xarray as xr


# Files are normally stored under daily fYYYYMMDD folders. The extractor
# falls back to this recursive glob when no matching daily-folder files exist.
ROMS_GLOB = "**/*.nc"

# Maximum allowed separation between a WOD cast and the closest ROMS output.
# Set to None to disable the check.
MAX_TIME_DIFFERENCE = pd.Timedelta("24h")
WET_CELL_SEARCH_RADIUS = 1

# -----------------------------------------------------------------------------
# HELPERS
# -----------------------------------------------------------------------------
def to_datetime64_ns(value):
    """Convert one time-like value to numpy datetime64[ns]."""
    return np.datetime64(pd.to_datetime(value).to_datetime64(), "ns")


def get_wod_profile_value(ds, name, profile_index):
    """Return one scalar WOD cast-level value by positional cast index."""
    da = ds[name]

    if "casts" not in da.dims:
        raise ValueError(
            f"WOD variable {name!r} is expected to use the 'casts' dimension; "
            f"found dims={da.dims}."
        )

    value = da.isel(casts=profile_index).values
    return np.asarray(value).squeeze().item()


def decode_roms_time(ds):
    """Read the single/first timestamp from a postprocessed ROMS file."""
    if "TSTEP" not in ds:
        raise KeyError("TSTEP not found")

    t = ds["TSTEP"].isel(TSTEP=0).values

    # With decode_times=True this should already be datetime64.
    if np.issubdtype(np.asarray(t).dtype, np.datetime64):
        return pd.Timestamp(t)

    # Robust fallback if xarray did not decode the numeric time coordinate.
    units = ds["TSTEP"].attrs.get("units", "")
    match = re.match(r"seconds since\s+(.+)", units, flags=re.IGNORECASE)
    if match:
        origin = pd.Timestamp(match.group(1))
        return origin + pd.to_timedelta(float(t), unit="s")

    raise ValueError(f"Could not decode TSTEP={t!r}; units={units!r}")


def build_roms_time_index(files, cache_file, roms_dir, roms_glob):
    """
    Build a table with one row per ROMS file: [time, file].

    The table is cached because opening thousands of NetCDF headers can take
    time. Delete the cache if ROMS files are added/replaced.
    """
    if cache_file.exists():
        print(f"Reading cached ROMS time index: {cache_file}")
        idx = pd.read_csv(cache_file, parse_dates=["time"])
        idx["file"] = idx["file"].astype(str)
        return idx.sort_values("time").reset_index(drop=True)

    records = []
    nfiles = len(files)
    print(f"Building ROMS time index from {nfiles} files ...")

    for n, fn in enumerate(files, 1):
        try:
            with xr.open_dataset(fn, decode_times=True) as ds:
                if not {"TEMP", "SALT", "TSTEP"}.issubset(ds.variables):
                    continue
                t = decode_roms_time(ds)
            records.append((t, str(fn)))
        except Exception as exc:
            print(f"WARNING: skipping {fn}: {exc}")

        if n % 500 == 0 or n == nfiles:
            print(f"  inspected {n}/{nfiles} files")

    if not records:
        raise RuntimeError(
            "No valid postprocessed ROMS files containing TEMP, SALT and TSTEP "
            f"were found under {roms_dir} with glob {roms_glob!r}."
        )

    idx = pd.DataFrame(records, columns=["time", "file"])
    idx = idx.sort_values("time").drop_duplicates(subset="file").reset_index(drop=True)
    idx.to_csv(cache_file, index=False)
    print(f"Saved ROMS time index: {cache_file}")
    return idx


def find_roms_files(roms_dir, roms_glob, start_time, end_time):
    """Find ROMS files only in daily folders overlapping the requested dates."""
    if start_time is None:
        return sorted(roms_dir.glob(roms_glob))

    first_day = start_time.normalize()
    last_day = (end_time - pd.Timedelta(nanoseconds=1)).normalize()
    daily_dirs = [
        roms_dir / f"f{day:%Y%m%d}"
        for day in pd.date_range(first_day, last_day, freq="D")
    ]
    print(
        f"Searching daily ROMS directories f{first_day:%Y%m%d} "
        f"through f{last_day:%Y%m%d} ..."
    )

    files = []
    for daily_dir in daily_dirs:
        if daily_dir.is_dir():
            files.extend(daily_dir.glob(roms_glob))

    files = sorted(set(files))
    if files:
        print(f"Found {len(files)} candidate ROMS files in requested daily directories.")
        return files

    print(
        "WARNING: no date-specific ROMS files found; "
        f"falling back to full search under {roms_dir}."
    )
    return sorted(roms_dir.glob(roms_glob))


def nearest_file(target_time, roms_index):
    """Return closest ROMS file, model time, and absolute time difference."""
    times = roms_index["time"].values.astype("datetime64[ns]")
    target = to_datetime64_ns(target_time)

    i = int(np.argmin(np.abs(times - target)))
    model_time = pd.Timestamp(roms_index.iloc[i]["time"])
    dt = abs(model_time - pd.Timestamp(target_time))
    return Path(roms_index.iloc[i]["file"]), model_time, dt


def nearest_1d_index(values, target):
    """Index of nearest value in a 1-D coordinate."""
    values = np.asarray(values, dtype=float)
    return int(np.nanargmin(np.abs(values - float(target))))


def haversine_distance_km(lon1, lat1, lon2, lat2):
    """Calculate great-circle distance between two points in kilometers."""
    earth_radius_km = 6371.0088
    lon1, lat1, lon2, lat2 = np.deg2rad([lon1, lat1, lon2, lat2])
    delta_lon = (lon2 - lon1 + np.pi) % (2 * np.pi) - np.pi
    delta_lat = lat2 - lat1
    a = (
        np.sin(delta_lat / 2) ** 2
        + np.cos(lat1) * np.cos(lat2) * np.sin(delta_lon / 2) ** 2
    )
    return float(2 * earth_radius_km * np.arcsin(np.sqrt(a)))


def profile_has_valid_ocean_data(temp, salt):
    """Return whether a profile has at least one finite, non-fill T/S level."""
    temp = np.asarray(temp, dtype=float)
    salt = np.asarray(salt, dtype=float)
    valid = np.isfinite(temp) & np.isfinite(salt)
    valid &= (temp != 0.0) | (salt != 0.0)
    return bool(np.any(valid))


def nearest_valid_grid_cell(
    lat_values,
    lon_values,
    temp_patch,
    salt_patch,
    row_start,
    col_start,
    target_lat,
    target_lon,
):
    """Choose the nearest wet cell in a loaded grid patch, if one is valid."""
    candidates = []
    for local_row in range(temp_patch.shape[1]):
        row = row_start + local_row
        for local_col in range(temp_patch.shape[2]):
            col = col_start + local_col
            temp_profile = temp_patch[:, local_row, local_col]
            salt_profile = salt_patch[:, local_row, local_col]
            if not profile_has_valid_ocean_data(temp_profile, salt_profile):
                continue

            model_lat = float(lat_values[row])
            model_lon = float(lon_values[col])
            distance = haversine_distance_km(
                target_lon, target_lat, model_lon, model_lat
            )
            candidates.append((distance, row, col))

    if not candidates:
        return None
    return min(candidates)


def date_window(start, end):
    """Return an inclusive YYYYMMDD range as a half-open timestamp interval."""
    if (start is None) != (end is None):
        raise ValueError("--start and --end must be supplied together.")
    if start is None:
        return None, None

    start_time = pd.to_datetime(start, format="%Y%m%d", errors="raise")
    end_time = pd.to_datetime(end, format="%Y%m%d", errors="raise")
    if start_time > end_time:
        raise ValueError("--start must be earlier than or equal to --end.")
    return start_time, end_time + pd.Timedelta(days=1)


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", help="First hindcast day, YYYYMMDD (inclusive)")
    parser.add_argument("--end", help="Last hindcast day, YYYYMMDD (inclusive)")
    parser.add_argument(
        "--wod-file",
        type=Path,
        required=True,
        help="Shared WOD CTD NetCDF input file.",
    )
    parser.add_argument(
        "--roms-dir",
        type=Path,
        required=True,
        help="Postprocessed ROMS ocean3d directory (normally $CAWO_POST/ocean3d).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory for extracted per-cast ROMS profiles.",
    )
    parser.add_argument("--roms-glob", default=ROMS_GLOB)
    args = parser.parse_args()

    start_time, end_time = date_window(args.start, args.end)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    roms_files = find_roms_files(
        args.roms_dir, args.roms_glob, start_time, end_time
    )
    if not roms_files:
        raise FileNotFoundError(
            f"No files found under {args.roms_dir} using pattern {args.roms_glob!r}."
        )

    time_cache = args.output_dir / "roms_postprocessed_time_index.csv"
    roms_index = build_roms_time_index(
        roms_files, time_cache, args.roms_dir, args.roms_glob
    )
    if start_time is not None:
        roms_index = roms_index[
            (roms_index["time"] >= start_time) & (roms_index["time"] < end_time)
        ].reset_index(drop=True)
        if roms_index.empty:
            raise RuntimeError(
                f"No postprocessed ROMS timestamps found between "
                f"{args.start} and {args.end} in {args.roms_dir}."
            )
    print(
        f"ROMS coverage: {roms_index['time'].min()} to "
        f"{roms_index['time'].max()} ({len(roms_index)} files)"
    )

    with xr.open_dataset(args.wod_file, decode_times=True, decode_timedelta=True) as ds_wod:
        # This WOD OCLDB aggregate uses "casts" as a dimension, but it does not
        # provide meaningful coordinate values for that dimension.  Therefore
        # casts must be accessed positionally with isel(casts=...).
        if "casts" not in ds_wod.dims:
            raise KeyError(
                "Expected the WOD file to contain a 'casts' dimension. "
                f"Found dimensions: {dict(ds_wod.sizes)}"
            )

        for required in ("time", "lon", "lat", "wod_unique_cast"):
            if required not in ds_wod.variables:
                raise KeyError(f"Expected WOD variable {required!r}.")

        ncasts = int(ds_wod.sizes["casts"])
        print(f"WOD casts: {ncasts}")
        print(
            f"WOD coverage: {pd.Timestamp(ds_wod['time'].isel(casts=0).values)} to "
            f"{pd.Timestamp(ds_wod['time'].isel(casts=-1).values)}"
        )

        n_written = 0
        n_skipped = 0

        for icast in range(ncasts):
            n = icast + 1
            try:
                # wod_unique_cast is the actual WOD profile identifier.
                cast_id = int(get_wod_profile_value(ds_wod, "wod_unique_cast", icast))
                target_time = pd.Timestamp(get_wod_profile_value(ds_wod, "time", icast))
                target_lon = float(get_wod_profile_value(ds_wod, "lon", icast))
                target_lat = float(get_wod_profile_value(ds_wod, "lat", icast))

                if pd.isna(target_time) or not np.isfinite(target_lon) or not np.isfinite(target_lat):
                    raise ValueError("invalid WOD time/lon/lat")
                if start_time is not None and not (start_time <= target_time < end_time):
                    continue

                roms_file, model_time, time_diff = nearest_file(target_time, roms_index)

                if MAX_TIME_DIFFERENCE is not None and time_diff > MAX_TIME_DIFFERENCE:
                    print(
                        f"SKIP cast {cast_id}: closest ROMS time {model_time} is "
                        f"{time_diff} away from WOD time {target_time}"
                    )
                    n_skipped += 1
                    continue

                with xr.open_dataset(roms_file, decode_times=True) as ds_roms:
                    for required in ("TEMP", "SALT", "lat", "lon", "LAY"):
                        if required not in ds_roms:
                            raise KeyError(f"{required!r} missing from {roms_file}")

                    # Search only the nearest cell and its immediate neighbors.
                    lat_values = np.asarray(ds_roms["lat"].values, dtype=float)
                    lon_values = np.asarray(ds_roms["lon"].values, dtype=float)
                    center_row = nearest_1d_index(lat_values, target_lat)
                    center_col = nearest_1d_index(lon_values, target_lon)
                    row_start = max(0, center_row - WET_CELL_SEARCH_RADIUS)
                    row_stop = min(
                        len(lat_values), center_row + WET_CELL_SEARCH_RADIUS + 1
                    )
                    col_start = max(0, center_col - WET_CELL_SEARCH_RADIUS)
                    col_stop = min(
                        len(lon_values), center_col + WET_CELL_SEARCH_RADIUS + 1
                    )

                    nearby = ds_roms[["TEMP", "SALT"]].isel(
                        TSTEP=0,
                        ROW=slice(row_start, row_stop),
                        COL=slice(col_start, col_stop),
                    ).load()
                    selected = nearest_valid_grid_cell(
                        lat_values,
                        lon_values,
                        nearby["TEMP"].values,
                        nearby["SALT"].values,
                        row_start,
                        col_start,
                        target_lat,
                        target_lon,
                    )
                    if selected is None:
                        print(
                            f"SKIP cast {cast_id}: no valid ROMS ocean profile "
                            f"within {WET_CELL_SEARCH_RADIUS} grid cell(s) of "
                            f"WOD position ({target_lon:.4f}, {target_lat:.4f})."
                        )
                        n_skipped += 1
                        continue

                    grid_distance_km, irow, icol = selected
                    profile = nearby[["TEMP", "SALT"]].isel(
                        ROW=irow - row_start, COL=icol - col_start
                    ).load()

                    model_lat = float(ds_roms["lat"].isel(ROW=irow).values)
                    model_lon = float(ds_roms["lon"].isel(COL=icol).values)
                    model_depth = ds_roms["LAY"].values.astype("float32")

                # Build a compact cast/profile file with useful matching metadata.
                out = xr.Dataset(
                    data_vars={
                        "TEMP": ("depth", np.asarray(profile["TEMP"].values, dtype="float32")),
                        "SALT": ("depth", np.asarray(profile["SALT"].values, dtype="float32")),
                    },
                    coords={
                        # Positive downward is easier to compare directly with WOD depth.
                        "depth": ("depth", -model_depth),
                    },
                    attrs={
                        "wod_cast": str(cast_id),
                        "wod_profile_index": int(icast),
                        "wod_time": target_time.isoformat(),
                        "wod_lon": target_lon,
                        "wod_lat": target_lat,
                        "roms_time": model_time.isoformat(),
                        "roms_lon": model_lon,
                        "roms_lat": model_lat,
                        "roms_grid_distance_km": grid_distance_km,
                        "time_difference_hours": time_diff.total_seconds() / 3600.0,
                        "source_roms_file": str(roms_file),
                        "source_wod_file": str(args.wod_file),
                    },
                )

                out["depth"].attrs.update(
                    units="m",
                    positive="down",
                    long_name="ROMS postprocessed fixed depth",
                )
                out["TEMP"].attrs.update(profile["TEMP"].attrs)
                out["SALT"].attrs.update(profile["SALT"].attrs)

                outfile = args.output_dir / f"roms_wod_cast_{cast_id}.nc"
                out.to_netcdf(outfile)
                out.close()

                n_written += 1
                print(
                    f"[{n}/{ncasts}] cast {cast_id}: "
                    f"WOD={target_time}, ROMS={model_time}, "
                    f"dt={time_diff}, grid=({model_lon:.4f}, {model_lat:.4f}), "
                    f"grid_distance={grid_distance_km:.3f} km"
                )

            except Exception as exc:
                print(f"WARNING: WOD profile index {icast} failed: {exc}")
                n_skipped += 1

    print("\nFinished")
    print(f"  written: {n_written}")
    print(f"  skipped/failed: {n_skipped}")
    print(f"  output directory: {args.output_dir}")


if __name__ == "__main__":
    main()
