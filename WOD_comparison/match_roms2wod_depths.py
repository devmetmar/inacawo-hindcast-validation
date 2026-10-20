#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Depth-match postprocessed ROMS profiles to WOD CTD observations.

Unlike the previous interp_roms2wod.py workflow, this script DOES NOT
interpolate ROMS vertically.  The postprocessed ROMS files already contain a
small set of fixed z levels (for example 0, 10, 25, 50, 100, 250, 500, 1000,
2000 m).  For each ROMS level, this script finds a WOD observation within
MAX_DEPTH_DIFFERENCE_M and retains the nearest valid depth match.

A one-to-one depth assignment is used: a single WOD depth observation cannot
be assigned to two different ROMS levels in the same cast.

Input ROMS files are the per-cast files produced by
extract_postprocessed_roms2wod.py, e.g.:
    roms_wod_cast_8345428.nc

Output files contain ROMS and WOD values side-by-side on a "match" dimension.
Only successfully depth-matched levels are written.

CHANGES vs the original version
--------------------------------
1. Defensive fill-value screen. extract_postprocessed_roms2wod.py searches
   the nearest grid cell and immediate neighbors for a valid profile. This
   script re-checks extracted profiles and skips all-fill (e.g. all-zero)
   profiles so invalid data cannot silently enter the comparison.
2. TEOS-10 (gsw) fields. ROMS TEMP/SALT are almost certainly *potential*
   temperature and *practical* salinity (the standard ROMS prognostic
   variables), whereas WOD Temperature is measured in-situ. This script now
   also writes:
     - roms_temp_insitu : ROMS potential temperature converted to in-situ
                           temperature at each matched depth/lat/lon
     - roms_sa           : ROMS practical salinity converted to Absolute
                            Salinity (SA)
     - wod_sa             : WOD practical salinity converted to Absolute
                             Salinity (SA), so ROMS and WOD salinity are
                             compared on the same footing
   The original roms_temp / roms_salt / wod_temp / wod_salt fields are kept
   unchanged so any existing downstream code keeps working; the new fields
   are additive. See add_teos10_fields() for the assumptions this rests on
   -- please confirm them against your ROMS configuration.
"""

from pathlib import Path
import argparse
import numpy as np
import pandas as pd
import xarray as xr
import gsw


MAX_DEPTH_DIFFERENCE_M = 5.0

# Same fill-value convention as extract_postprocessed_roms2wod.py. Kept in
# sync here so this script can screen a cast even if it was produced by an
# older/unpatched extraction run.
LAND_FILL_VALUE = 0.0


# -----------------------------------------------------------------------------
# HELPERS
# -----------------------------------------------------------------------------
def ragged_start_indices(row_sizes):
    """Return the starting flat-array index for every ragged profile."""
    row_sizes = np.asarray(row_sizes, dtype=np.int64)
    starts = np.zeros(row_sizes.size, dtype=np.int64)
    if row_sizes.size > 1:
        starts[1:] = np.cumsum(row_sizes[:-1])
    return starts


def read_ragged_row_sizes(ds, name):
    """Read ragged row sizes, treating missing profiles as zero-length rows."""
    values = np.asarray(ds[name].values, dtype=float)
    missing = ~np.isfinite(values)
    if missing.any():
        print(
            f"WARNING: {name} has {int(missing.sum())} missing row sizes; "
            "treating them as empty profiles."
        )
        values[missing] = 0
    if np.any(values < 0) or np.any(values != np.floor(values)):
        raise ValueError(f"{name} must contain non-negative integer row sizes.")
    return values.astype(np.int64)


def get_cast_slice(values, starts, row_sizes, icast):
    """Extract one cast from a contiguous ragged array."""
    n = int(row_sizes[icast])
    i0 = int(starts[icast])
    i1 = i0 + n
    return np.asarray(values[i0:i1])


def one_to_one_depth_matches(model_depths, wod_depths, tolerance):
    """
    Match model depths to WOD depths within a maximum vertical separation.

    Candidate model/WOD pairs within `tolerance` are sorted by absolute depth
    difference.  The closest pairs are accepted first, while ensuring that
    each model level and each WOD observation are used at most once.

    Returns
    -------
    list of tuples
        (model_index, wod_index, absolute_depth_difference), sorted by model
        depth/index.
    """
    model_depths = np.asarray(model_depths, dtype=float)
    wod_depths = np.asarray(wod_depths, dtype=float)

    candidates = []
    for im, zm in enumerate(model_depths):
        if not np.isfinite(zm):
            continue
        for iw, zw in enumerate(wod_depths):
            if not np.isfinite(zw):
                continue
            dz = abs(float(zw) - float(zm))
            if dz <= tolerance:
                candidates.append((dz, im, iw))

    # Closest pairs first. Secondary keys make ties deterministic.
    candidates.sort(key=lambda x: (x[0], x[1], x[2]))

    used_model = set()
    used_wod = set()
    accepted = []

    for dz, im, iw in candidates:
        if im in used_model or iw in used_wod:
            continue
        used_model.add(im)
        used_wod.add(iw)
        accepted.append((im, iw, dz))

    accepted.sort(key=lambda x: x[0])
    return accepted


def safe_cast_scalar(ds, name, icast, default=np.nan):
    """Read a cast-level scalar if present."""
    if name not in ds:
        return default
    try:
        value = ds[name].isel(casts=icast).values
        scalar = np.asarray(value).squeeze()
        if np.issubdtype(scalar.dtype, np.datetime64):
            return pd.Timestamp(scalar).isoformat()
        return scalar.item()
    except Exception:
        return default


def looks_like_fill(temp, salt, fill_value=LAND_FILL_VALUE):
    """Same heuristic as extract_postprocessed_roms2wod.py.looks_like_fill()."""
    finite_t = np.isfinite(temp)
    finite_s = np.isfinite(salt)

    if not finite_t.any() and not finite_s.any():
        return True

    all_fill_t = np.all(temp[finite_t] == fill_value) if finite_t.any() else True
    all_fill_s = np.all(salt[finite_s] == fill_value) if finite_s.any() else True
    return all_fill_t and all_fill_s


def add_teos10_fields(roms_depth, roms_theta, roms_sp, wod_depth, wod_sp, lat, lon):
    """
    Convert ROMS potential temperature/practical salinity to in-situ
    temperature/Absolute Salinity, and WOD practical salinity to Absolute
    Salinity, using TEOS-10 (gsw).

    Assumptions -- confirm these against your setup before trusting the
    output:
      * roms_theta is potential temperature referenced to the sea surface
        (0 dbar). This is the standard ROMS prognostic temperature.
      * roms_sp and wod_sp are Practical Salinity (PSS-78), which is what
        ROMS carries as its salinity state variable and what a CTD reports
        before any TEOS-10 processing.
      * wod_temp (not touched here) is already in-situ temperature, i.e. no
        conversion is applied to it.
      * depth arrays are positive-down, consistent with the rest of this
        pipeline; gsw wants height z (negative in the ocean), hence -depth.

    Returns
    -------
    roms_sa, roms_temp_insitu, wod_sa : np.ndarray
        Same shape as the inputs. NaN propagates through for any input that
        was itself NaN.
    """
    roms_depth = np.asarray(roms_depth, dtype=float)
    roms_theta = np.asarray(roms_theta, dtype=float)
    roms_sp = np.asarray(roms_sp, dtype=float)
    wod_depth = np.asarray(wod_depth, dtype=float)
    wod_sp = np.asarray(wod_sp, dtype=float)

    p_roms = gsw.p_from_z(-roms_depth, lat)
    sa_roms = gsw.SA_from_SP(roms_sp, p_roms, lon, lat)
    ct_roms = gsw.CT_from_pt(sa_roms, roms_theta)
    t_roms_insitu = gsw.t_from_CT(sa_roms, ct_roms, p_roms)

    p_wod = gsw.p_from_z(-wod_depth, lat)
    sa_wod = gsw.SA_from_SP(wod_sp, p_wod, lon, lat)

    return (
        np.asarray(sa_roms, dtype=np.float32),
        np.asarray(t_roms_insitu, dtype=np.float32),
        np.asarray(sa_wod, dtype=np.float32),
    )


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
        "--roms-extracted-dir",
        type=Path,
        required=True,
        help="Directory containing extracted per-cast ROMS profiles.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory for depth-matched per-cast output files.",
    )
    args = parser.parse_args()

    start_time, end_time = date_window(args.start, args.end)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    with xr.open_dataset(args.wod_file, decode_times=True, decode_timedelta=True) as ds_wod:
        required = [
            "wod_unique_cast",
            "time",
            "lat",
            "lon",
            "z",
            "z_row_size",
            "Temperature",
            "Temperature_row_size",
            "Salinity",
            "Salinity_row_size",
        ]
        missing = [name for name in required if name not in ds_wod]
        if missing:
            raise KeyError(f"Missing required WOD variables: {missing}")

        ncasts = int(ds_wod.sizes["casts"])

        # Ragged-array row sizes and start positions.
        z_row_size = read_ragged_row_sizes(ds_wod, "z_row_size")
        t_row_size = read_ragged_row_sizes(ds_wod, "Temperature_row_size")
        s_row_size = read_ragged_row_sizes(ds_wod, "Salinity_row_size")

        z_start = ragged_start_indices(z_row_size)
        t_start = ragged_start_indices(t_row_size)
        s_start = ragged_start_indices(s_row_size)

        # Flat ragged arrays. Load once to avoid repeated disk reads.
        wod_z_all = ds_wod["z"].values
        wod_t_all = ds_wod["Temperature"].values
        wod_s_all = ds_wod["Salinity"].values

        wod_t_flag_all = (
            ds_wod["Temperature_WODflag"].values
            if "Temperature_WODflag" in ds_wod
            else None
        )
        wod_s_flag_all = (
            ds_wod["Salinity_WODflag"].values
            if "Salinity_WODflag" in ds_wod
            else None
        )

        print(f"WOD casts: {ncasts}")
        print(f"Maximum allowed depth difference: {MAX_DEPTH_DIFFERENCE_M:.1f} m")
        print(f"ROMS extracted directory: {args.roms_extracted_dir}")
        print(f"Output directory: {args.output_dir}")

        n_written = 0
        n_no_roms = 0
        n_no_match = 0
        n_fill = 0
        total_matches = 0

        for icast in range(ncasts):
            cast_id = int(ds_wod["wod_unique_cast"].isel(casts=icast).values)
            wod_time = pd.Timestamp(ds_wod["time"].isel(casts=icast).values)
            if start_time is not None and not (start_time <= wod_time < end_time):
                continue
            roms_file = args.roms_extracted_dir / f"roms_wod_cast_{cast_id}.nc"

            if not roms_file.exists():
                n_no_roms += 1
                continue

            # -------------------------------------------------------------
            # WOD depth profile for this cast
            # -------------------------------------------------------------
            wod_depth = get_cast_slice(wod_z_all, z_start, z_row_size, icast).astype(float)

            if wod_depth.size == 0 or not np.any(np.isfinite(wod_depth)):
                n_no_match += 1
                continue

            # Temperature and salinity use the same z sequence whenever that
            # variable is present in this WOD file.  If a malformed/empty
            # ragged slice is encountered, keep the cast and mark only that
            # variable as missing rather than aborting the complete run.
            def read_wod_variable(values_all, flags_all, starts, row_sizes, varname):
                n_expected = int(row_sizes[icast])

                if n_expected <= 0:
                    return (
                        np.full(wod_depth.size, np.nan, dtype=float),
                        np.full(wod_depth.size, -1, dtype=np.int16),
                    )

                vals = get_cast_slice(values_all, starts, row_sizes, icast).astype(float)

                if vals.size != wod_depth.size:
                    print(
                        f"WARNING cast {cast_id}: {varname} slice has {vals.size} values "
                        f"but depth has {wod_depth.size}; treating {varname} as missing."
                    )
                    return (
                        np.full(wod_depth.size, np.nan, dtype=float),
                        np.full(wod_depth.size, -1, dtype=np.int16),
                    )

                if flags_all is not None:
                    flags = get_cast_slice(flags_all, starts, row_sizes, icast)
                    if flags.size == wod_depth.size:
                        flags = flags.astype(np.int16)
                    else:
                        flags = np.full(wod_depth.size, -1, dtype=np.int16)
                else:
                    flags = np.full(wod_depth.size, -1, dtype=np.int16)

                return vals, flags

            wod_temp, wod_temp_flag = read_wod_variable(
                wod_t_all, wod_t_flag_all, t_start, t_row_size, "Temperature"
            )
            wod_salt, wod_salt_flag = read_wod_variable(
                wod_s_all, wod_s_flag_all, s_start, s_row_size, "Salinity"
            )

            # -------------------------------------------------------------
            # ROMS fixed-depth profile already collocated in time/space
            # -------------------------------------------------------------
            with xr.open_dataset(roms_file) as ds_roms:
                for name in ("depth", "TEMP", "SALT"):
                    if name not in ds_roms:
                        raise KeyError(f"{name!r} missing from {roms_file}")

                roms_depth = np.asarray(ds_roms["depth"].values, dtype=float)
                roms_temp = np.asarray(ds_roms["TEMP"].values, dtype=float).squeeze()
                roms_salt = np.asarray(ds_roms["SALT"].values, dtype=float).squeeze()
                roms_attrs = dict(ds_roms.attrs)

            if looks_like_fill(roms_temp, roms_salt):
                print(
                    f"SKIP cast {cast_id}: extracted ROMS profile is all fill "
                    f"({LAND_FILL_VALUE}); no usable temperature/salinity values."
                )
                n_fill += 1
                continue

            # Safety in case a depth coordinate were accidentally negative-down.
            if np.nanmin(roms_depth) < 0:
                roms_depth = np.abs(roms_depth)

            matches = one_to_one_depth_matches(
                roms_depth,
                wod_depth,
                MAX_DEPTH_DIFFERENCE_M,
            )

            if not matches:
                n_no_match += 1
                continue

            im = np.asarray([m[0] for m in matches], dtype=np.int32)
            iw = np.asarray([m[1] for m in matches], dtype=np.int32)
            dz = np.asarray([m[2] for m in matches], dtype=np.float32)

            wod_lat = float(safe_cast_scalar(ds_wod, "lat", icast))
            wod_lon = float(safe_cast_scalar(ds_wod, "lon", icast))

            matched_roms_depth = roms_depth[im]
            matched_wod_depth = wod_depth[iw]
            matched_roms_temp = roms_temp[im]
            matched_roms_salt = roms_salt[im]
            matched_wod_temp = wod_temp[iw]
            matched_wod_salt = wod_salt[iw]

            roms_sa, roms_temp_insitu, wod_sa = add_teos10_fields(
                roms_depth=matched_roms_depth,
                roms_theta=matched_roms_temp,
                roms_sp=matched_roms_salt,
                wod_depth=matched_wod_depth,
                wod_sp=matched_wod_salt,
                lat=wod_lat,
                lon=wod_lon,
            )

            # -------------------------------------------------------------
            # Output: only matched depth levels
            # -------------------------------------------------------------
            out = xr.Dataset(
                data_vars={
                    "roms_temp": ("match", matched_roms_temp.astype(np.float32)),
                    "wod_temp": ("match", matched_wod_temp.astype(np.float32)),
                    "roms_salt": ("match", matched_roms_salt.astype(np.float32)),
                    "wod_salt": ("match", matched_wod_salt.astype(np.float32)),
                    # TEOS-10 converted fields (see add_teos10_fields() docstring
                    # for the assumptions these rest on).
                    "roms_temp_insitu": ("match", roms_temp_insitu),
                    "roms_sa": ("match", roms_sa),
                    "wod_sa": ("match", wod_sa),
                    "wod_temp_flag": ("match", wod_temp_flag[iw].astype(np.int16)),
                    "wod_salt_flag": ("match", wod_salt_flag[iw].astype(np.int16)),
                    "depth_difference": ("match", dz),
                    "wod_depth_index_in_cast": ("match", iw.astype(np.int32)),
                    "roms_depth_index": ("match", im.astype(np.int32)),
                },
                coords={
                    "match": np.arange(len(matches), dtype=np.int32),
                    "roms_depth": ("match", matched_roms_depth.astype(np.float32)),
                    "wod_depth": ("match", matched_wod_depth.astype(np.float32)),
                },
                attrs={
                    "wod_cast": str(cast_id),
                    "wod_profile_index": int(icast),
                    "wod_time": wod_time.isoformat(),
                    "wod_lat": wod_lat,
                    "wod_lon": wod_lon,
                    "max_depth_difference_m": float(MAX_DEPTH_DIFFERENCE_M),
                    "depth_matching_method": (
                        "Nearest WOD depth to each ROMS fixed depth within tolerance; "
                        "one-to-one assignment, no vertical interpolation"
                    ),
                    "teos10_note": (
                        "roms_temp_insitu/roms_sa/wod_sa were derived with gsw "
                        "assuming roms_temp is potential temperature and "
                        "roms_salt/wod_salt are Practical Salinity. Verify these "
                        "assumptions against your ROMS EOS configuration."
                    ),
                    "source_wod_file": str(args.wod_file),
                    "source_roms_file": str(roms_file),
                    "roms_time": str(roms_attrs.get("roms_time", "")),
                    "roms_lat": roms_attrs.get("roms_lat", np.nan),
                    "roms_lon": roms_attrs.get("roms_lon", np.nan),
                    "roms_grid_distance_km": roms_attrs.get(
                        "roms_grid_distance_km", np.nan
                    ),
                    "time_difference_hours": roms_attrs.get(
                        "time_difference_hours", np.nan
                    ),
                },
            )

            out["roms_depth"].attrs.update(units="m", positive="down")
            out["wod_depth"].attrs.update(units="m", positive="down")
            out["depth_difference"].attrs.update(
                units="m",
                long_name="absolute vertical separation between ROMS and WOD",
            )
            out["roms_temp"].attrs.update(units="degree_C", long_name="ROMS potential temperature")
            out["wod_temp"].attrs.update(units="degree_C", long_name="WOD in-situ temperature")
            out["roms_temp_insitu"].attrs.update(units="degree_C", long_name="ROMS in-situ temperature (TEOS-10)")
            out["roms_salt"].attrs.update(units="1", long_name="ROMS practical salinity")
            out["wod_salt"].attrs.update(units="1", long_name="WOD practical salinity")
            out["roms_sa"].attrs.update(units="g/kg", long_name="ROMS Absolute Salinity (TEOS-10)")
            out["wod_sa"].attrs.update(units="g/kg", long_name="WOD Absolute Salinity (TEOS-10)")

            outfile = args.output_dir / f"roms2wod_depthmatch_{cast_id}.nc"
            out.to_netcdf(outfile)
            out.close()

            n_written += 1
            total_matches += len(matches)

            print(
                f"[{icast + 1}/{ncasts}] cast {cast_id}: "
                f"{len(matches)} matched ROMS levels -> {outfile.name}"
            )

    print("\nFinished")
    print(f"  cast files written: {n_written}")
    print(f"  total matched depth pairs: {total_matches}")
    print(f"  casts without extracted ROMS file: {n_no_roms}")
    print(f"  casts skipped for all-fill ROMS profiles: {n_fill}")
    print(f"  casts with no depth match within {MAX_DEPTH_DIFFERENCE_M:.1f} m: {n_no_match}")
    print(f"  output directory: {args.output_dir}")


if __name__ == "__main__":
    main()
