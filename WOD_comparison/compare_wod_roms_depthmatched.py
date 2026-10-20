#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Compare WOD CTD observations with ROMS using the depth-matched files produced by
match_roms2wod_depths.py.

The matched files are expected to contain, for each accepted ROMS/WOD depth pair:

    roms_depth(match)
    wod_depth(match)
    depth_difference(match)

    roms_temp(match)
    wod_temp(match)
    wod_temp_flag(match)

    roms_salt(match)
    wod_salt(match)
    wod_salt_flag(match)

Expected input file names:
    roms2wod_depthmatch_*.nc

The script:
  1. Reads all matched cast files.
  2. Applies WOD QC: flag <= 0, finite WOD and ROMS values.
  3. Groups comparisons by fixed ROMS depth.
  4. Computes N, bias, RMSE, MAE, Pearson correlation, R2,
     WOD mean/std, ROMS mean/std, and mean/max depth mismatch.
  5. Makes a separate scatter plot for Temperature and Salinity at every depth.
  6. Makes all-depth scatter plots colored by ROMS depth.
  7. Makes mean vertical-profile plots using the depth-level averages.
  8. Writes CSV files containing all valid matched pairs and summary statistics.

Example:
    python compare_wod_roms_depthmatched.py \
        "$CAWO_HINDCAST_BASE/validation/wod_comparison/YYYYMMDD_YYYYMMDD/jobs/<job-id>_<restart>/roms_wod_depthmatched" \
        "$CAWO_HINDCAST_BASE/validation/wod_comparison/YYYYMMDD_YYYYMMDD/jobs/<job-id>_<restart>/comparison_depthmatched"

Optional:
    --years 1995 1996 1997
    --roms_glob "roms2wod_depthmatch_*.nc"
    --qc_max 0
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import sklearn.metrics as skm


# Fixed levels expected from the postprocessed ROMS data.
DEFAULT_ROMS_DEPTHS = np.array(
    [0.0, 10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 2000.0],
    dtype=float,
)

# Some depth-matched files from older runs can contain profiles written as
# exact fill values at every level (0.0 in this pipeline). QC screening below
# rejects those defensively, in addition to the upstream profile checks.
LAND_FILL_VALUE = 0.0


def parse_year(value) -> int | None:
    """Extract year from a time-like value/string. Return None if unavailable."""
    try:
        t = parse_timestamp(value)
        if pd.isna(t):
            return None
        return int(t.year)
    except Exception:
        return None


def parse_timestamp(value):
    """Parse ISO timestamps and legacy nanosecond timestamps stored as strings."""
    if isinstance(value, (int, np.integer)):
        return pd.to_datetime(value, unit="ns", errors="coerce")

    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit() or (
            stripped.startswith("-") and stripped[1:].isdigit()
        ):
            return pd.to_datetime(int(stripped), unit="ns", errors="coerce")

    return pd.to_datetime(value, errors="coerce")


def safe_float(value, default=np.nan):
    try:
        return float(value)
    except Exception:
        return float(default)


def compute_stats(obs: np.ndarray, mod: np.ndarray) -> dict:
    """Compute comparison statistics for paired finite arrays."""
    obs = np.asarray(obs, dtype=float)
    mod = np.asarray(mod, dtype=float)

    good = np.isfinite(obs) & np.isfinite(mod)
    obs = obs[good]
    mod = mod[good]

    n = obs.size

    if n == 0:
        return {
            "N": 0,
            "bias": np.nan,
            "rmse": np.nan,
            "mae": np.nan,
            "corr": np.nan,
            "r2": np.nan,
            "wod_mean": np.nan,
            "wod_std": np.nan,
            "roms_mean": np.nan,
            "roms_std": np.nan,
        }

    bias = float(np.mean(mod - obs))
    rmse = float(np.sqrt(np.mean((mod - obs) ** 2)))
    mae = float(np.mean(np.abs(mod - obs)))

    # Correlation needs at least 2 non-constant samples.
    if n >= 2 and np.nanstd(obs) > 0 and np.nanstd(mod) > 0:
        corr = float(np.corrcoef(obs, mod)[0, 1])
    else:
        corr = np.nan

    if n >= 2:
        try:
            r2 = float(skm.r2_score(obs, mod))
        except Exception:
            r2 = np.nan
    else:
        r2 = np.nan

    return {
        "N": int(n),
        "bias": bias,
        "rmse": rmse,
        "mae": mae,
        "corr": corr,
        "r2": r2,
        "wod_mean": float(np.mean(obs)),
        "wod_std": float(np.std(obs)),
        "roms_mean": float(np.mean(mod)),
        "roms_std": float(np.std(mod)),
    }


def padded_limits(obs: np.ndarray, mod: np.ndarray, fallback: tuple[float, float]):
    """Return common x/y limits suitable for a 1:1 scatter."""
    vals = np.concatenate(
        [
            np.asarray(obs, dtype=float).ravel(),
            np.asarray(mod, dtype=float).ravel(),
        ]
    )
    vals = vals[np.isfinite(vals)]

    if vals.size == 0:
        return fallback

    vmin = float(np.min(vals))
    vmax = float(np.max(vals))

    if np.isclose(vmin, vmax):
        pad = max(abs(vmin) * 0.05, 0.5)
    else:
        pad = 0.05 * (vmax - vmin)

    return vmin - pad, vmax + pad


def save_depth_scatter(
    df: pd.DataFrame,
    obs_col: str,
    mod_col: str,
    variable_label: str,
    units: str,
    depth: float,
    out_dir: Path,
    fallback_limits: tuple[float, float],
):
    """Save one WOD-vs-ROMS scatter plot for one ROMS depth."""
    stats = compute_stats(df[obs_col].values, df[mod_col].values)

    fig = plt.figure(figsize=(6, 5))
    ax = fig.add_subplot(111)

    ax.scatter(
        df[obs_col].values,
        df[mod_col].values,
        s=7,
        alpha=0.45,
        linewidths=0,
    )

    lo, hi = padded_limits(
        df[obs_col].values,
        df[mod_col].values,
        fallback=fallback_limits,
    )
    ax.plot([lo, hi], [lo, hi], "--", color="black", lw=1)
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)

    text = (
        f"N = {stats['N']}\n"
        f"Bias = {stats['bias']:.3f}\n"
        f"RMSE = {stats['rmse']:.3f}\n"
        f"MAE = {stats['mae']:.3f}\n"
        f"r = {stats['corr']:.3f}\n"
        f"R² = {stats['r2']:.3f}"
    )
    ax.text(
        0.04,
        0.96,
        text,
        transform=ax.transAxes,
        va="top",
        ha="left",
        bbox=dict(boxstyle="round", facecolor="white", alpha=0.85),
    )

    ax.set_xlabel(f"WOD {variable_label} ({units})" if units else f"WOD {variable_label}")
    ax.set_ylabel(f"ROMS {variable_label} ({units})" if units else f"ROMS {variable_label}")
    ax.set_title(f"ROMS vs WOD {variable_label} | {depth:g} m")
    ax.grid(alpha=0.2)

    out_png = out_dir / f"{variable_label.lower()}_wod_x_roms_{depth:g}m.png"
    fig.savefig(out_png, dpi=200, bbox_inches="tight")
    plt.close(fig)


def save_all_depth_scatter(
    df: pd.DataFrame,
    obs_col: str,
    mod_col: str,
    variable_label: str,
    units: str,
    out_dir: Path,
    fallback_limits: tuple[float, float],
):
    """Scatter using all depth levels, colored by ROMS depth."""
    stats = compute_stats(df[obs_col].values, df[mod_col].values)

    fig = plt.figure(figsize=(6.4, 5.2))
    ax = fig.add_subplot(111)

    sc = ax.scatter(
        df[obs_col].values,
        df[mod_col].values,
        c=df["roms_depth"].values,
        s=6,
        alpha=0.5,
        linewidths=0,
        cmap="viridis",
    )

    lo, hi = padded_limits(
        df[obs_col].values,
        df[mod_col].values,
        fallback=fallback_limits,
    )
    ax.plot([lo, hi], [lo, hi], "--", color="black", lw=1)
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)

    text = (
        f"N = {stats['N']}\n"
        f"Bias = {stats['bias']:.3f}\n"
        f"RMSE = {stats['rmse']:.3f}\n"
        f"MAE = {stats['mae']:.3f}\n"
        f"r = {stats['corr']:.3f}\n"
        f"R² = {stats['r2']:.3f}"
    )
    ax.text(
        0.04,
        0.96,
        text,
        transform=ax.transAxes,
        va="top",
        ha="left",
        bbox=dict(boxstyle="round", facecolor="white", alpha=0.85),
    )

    cbar = plt.colorbar(sc, ax=ax)
    cbar.set_label("ROMS depth (m)")

    ax.set_xlabel(f"WOD {variable_label} ({units})" if units else f"WOD {variable_label}")
    ax.set_ylabel(f"ROMS {variable_label} ({units})" if units else f"ROMS {variable_label}")
    ax.set_title(f"ROMS vs WOD {variable_label} | All matched depths")
    ax.grid(alpha=0.2)

    out_png = out_dir / f"{variable_label.lower()}_wod_x_roms_ALL_depths.png"
    fig.savefig(out_png, dpi=200, bbox_inches="tight")
    plt.close(fig)


def save_mean_profile(
    stats_df: pd.DataFrame,
    variable_label: str,
    units: str,
    out_dir: Path,
):
    """Plot mean WOD and ROMS values versus the fixed ROMS depth levels."""
    good = stats_df[stats_df["N"] > 0].copy()
    if good.empty:
        return

    good = good.sort_values("roms_depth")

    fig = plt.figure(figsize=(5.2, 6.0))
    ax = fig.add_subplot(111)

    ax.errorbar(
        good["wod_mean"],
        good["roms_depth"],
        xerr=good["wod_std"],
        fmt="o-",
        capsize=2,
        label="WOD",
    )
    ax.errorbar(
        good["roms_mean"],
        good["roms_depth"],
        xerr=good["roms_std"],
        fmt="o-",
        capsize=2,
        label="ROMS",
    )

    ax.invert_yaxis()
    ax.set_ylabel("ROMS depth (m)")
    ax.set_xlabel(f"{variable_label} ({units})" if units else variable_label)
    ax.set_title(f"Mean vertical profile | {variable_label}")
    ax.grid(alpha=0.2)
    ax.legend()

    out_png = out_dir / f"{variable_label.lower()}_mean_profile.png"
    fig.savefig(out_png, dpi=200, bbox_inches="tight")
    plt.close(fig)


def save_metric_vs_depth(
    stats_df: pd.DataFrame,
    metric: str,
    variable_label: str,
    ylabel: str,
    out_dir: Path,
):
    good = stats_df[(stats_df["N"] > 0) & np.isfinite(stats_df[metric])].copy()
    if good.empty:
        return

    good = good.sort_values("roms_depth")

    fig = plt.figure(figsize=(5.2, 5.5))
    ax = fig.add_subplot(111)

    ax.plot(good[metric], good["roms_depth"], "o-")
    ax.invert_yaxis()
    ax.set_xlabel(ylabel)
    ax.set_ylabel("ROMS depth (m)")
    ax.set_title(f"{variable_label} {ylabel} by depth")
    ax.grid(alpha=0.2)

    out_png = out_dir / f"{variable_label.lower()}_{metric}_by_depth.png"
    fig.savefig(out_png, dpi=200, bbox_inches="tight")
    plt.close(fig)


def load_all_matches(
    input_dir: Path,
    roms_glob: str,
    selected_years: set[int] | None,
    start_time: pd.Timestamp | None,
    end_time: pd.Timestamp | None,
) -> pd.DataFrame:
    files = sorted(input_dir.glob(roms_glob))
    if not files:
        raise RuntimeError(
            f"No depth-matched cast files matching {roms_glob!r} were found in "
            f"{input_dir}. The comparison cannot be computed because the "
            "depth-matching stage produced no valid casts; review its log for "
            "casts skipped because extracted ROMS profiles contained only fill values."
        )

    records = []

    print(f"Matched cast files found: {len(files)}")

    for ifile, path in enumerate(files, start=1):
        try:
            with xr.open_dataset(path) as ds:
                required = [
                    "roms_depth",
                    "wod_depth",
                    "depth_difference",
                    "roms_temp",
                    "wod_temp",
                    "roms_salt",
                    "wod_salt",
                ]
                missing = [name for name in required if name not in ds]
                if missing:
                    print(f"  [WARN] {path.name}: missing {missing}; skipping")
                    continue

                nmatch = int(ds.sizes.get("match", 0))
                if nmatch == 0:
                    print(f"  [WARN] {path.name}: no matched depth levels; skipping")
                    continue

                wod_time = ds.attrs.get("wod_time", "")
                year = parse_year(wod_time)

                if start_time is not None:
                    cast_time = parse_timestamp(wod_time)
                    if pd.isna(cast_time):
                        print(
                            f"  [WARN] {path.name}: missing or invalid wod_time "
                            f"attribute {wod_time!r}; cannot apply date filter; skipping"
                        )
                        continue
                    if not (start_time <= cast_time < end_time):
                        print(
                            f"  [WARN] {path.name}: wod_time {cast_time} is outside "
                            "the requested date range; skipping"
                        )
                        continue

                if selected_years is not None:
                    if year is None or year not in selected_years:
                        continue

                cast_id = str(ds.attrs.get("wod_cast", path.stem))
                lat = safe_float(ds.attrs.get("wod_lat", np.nan))
                lon = safe_float(ds.attrs.get("wod_lon", np.nan))
                roms_time = ds.attrs.get("roms_time", "")
                time_difference_hours = safe_float(
                    ds.attrs.get("time_difference_hours", np.nan)
                )

                roms_depth = np.asarray(ds["roms_depth"].values, dtype=float).ravel()
                wod_depth = np.asarray(ds["wod_depth"].values, dtype=float).ravel()
                depth_difference = np.asarray(
                    ds["depth_difference"].values, dtype=float
                ).ravel()

                roms_temp = np.asarray(ds["roms_temp"].values, dtype=float).ravel()
                wod_temp = np.asarray(ds["wod_temp"].values, dtype=float).ravel()
                roms_salt = np.asarray(ds["roms_salt"].values, dtype=float).ravel()
                wod_salt = np.asarray(ds["wod_salt"].values, dtype=float).ravel()

                if "wod_temp_flag" in ds:
                    wod_temp_flag = np.asarray(
                        ds["wod_temp_flag"].values, dtype=float
                    ).ravel()
                else:
                    wod_temp_flag = np.full(nmatch, np.nan)

                if "wod_salt_flag" in ds:
                    wod_salt_flag = np.asarray(
                        ds["wod_salt_flag"].values, dtype=float
                    ).ravel()
                else:
                    wod_salt_flag = np.full(nmatch, np.nan)

                # Optional TEOS-10 converted fields (present if the matched
                # file was produced by the patched match_roms2wod_depths.py).
                # Fall back to NaN so older depth-matched files still load.
                def optional_var(name):
                    if name in ds:
                        return np.asarray(ds[name].values, dtype=float).ravel()
                    return np.full(nmatch, np.nan)

                roms_temp_insitu = optional_var("roms_temp_insitu")
                roms_sa = optional_var("roms_sa")
                wod_sa = optional_var("wod_sa")

                if not all(
                    arr.size == nmatch
                    for arr in (
                        roms_depth,
                        wod_depth,
                        depth_difference,
                        roms_temp,
                        wod_temp,
                        roms_salt,
                        wod_salt,
                        wod_temp_flag,
                        wod_salt_flag,
                        roms_temp_insitu,
                        roms_sa,
                        wod_sa,
                    )
                ):
                    print(
                        f"  [WARN] {path.name}: inconsistent match dimensions; skipping"
                    )
                    continue

                for i in range(nmatch):
                    records.append(
                        {
                            "source_file": path.name,
                            "cast_id": cast_id,
                            "year": year,
                            "wod_time": str(wod_time),
                            "roms_time": str(roms_time),
                            "lat": lat,
                            "lon": lon,
                            "time_difference_hours": time_difference_hours,
                            "roms_depth": float(roms_depth[i]),
                            "wod_depth": float(wod_depth[i]),
                            "depth_difference": float(depth_difference[i]),
                            "wod_temp": float(wod_temp[i]),
                            "roms_temp": float(roms_temp[i]),
                            "wod_temp_flag": float(wod_temp_flag[i]),
                            "wod_salt": float(wod_salt[i]),
                            "roms_salt": float(roms_salt[i]),
                            "wod_salt_flag": float(wod_salt_flag[i]),
                            "roms_temp_insitu": float(roms_temp_insitu[i]),
                            "roms_sa": float(roms_sa[i]),
                            "wod_sa": float(wod_sa[i]),
                        }
                    )

        except Exception as exc:
            print(f"  [WARN] Could not read {path.name}: {exc}")

        if ifile % 500 == 0 or ifile == len(files):
            print(f"  read {ifile}/{len(files)} files")

    if not records:
        raise RuntimeError("No usable matched records were read.")

    return pd.DataFrame.from_records(records)


def make_qc_table(
    df: pd.DataFrame, variable: str, qc_max: float, teos10: bool = False
) -> pd.DataFrame:
    if variable == "temp":
        obs_col = "wod_temp"
        # WOD temperature is already in-situ, so there is nothing to switch
        # to under --teos10; roms_temp_insitu is the fair comparison target.
        mod_col = "roms_temp_insitu" if teos10 else "roms_temp"
        flag_col = "wod_temp_flag"
    elif variable == "salt":
        obs_col = "wod_sa" if teos10 else "wod_salt"
        mod_col = "roms_sa" if teos10 else "roms_salt"
        flag_col = "wod_salt_flag"
    else:
        raise ValueError(variable)

    # Same basic rule as the previous workflow:
    # finite values + WOD flag <= qc_max.
    #
    # If a matched file has no QC flag variable at all, flag is NaN and the
    # point is rejected rather than silently treated as QC-passed.
    mask = (
        np.isfinite(df[obs_col].values)
        & np.isfinite(df[mod_col].values)
        & np.isfinite(df["roms_depth"].values)
        & np.isfinite(df["wod_depth"].values)
        & np.isfinite(df["depth_difference"].values)
        & np.isfinite(df[flag_col].values)
        & (df[flag_col].values <= qc_max)
    )

    # Reject matched pairs where both raw ROMS temperature and salinity are
    # exactly the fill value; isolated near-zero ocean values remain valid.
    invalid_roms_point = (df["roms_temp"].values == LAND_FILL_VALUE) & (
        df["roms_salt"].values == LAND_FILL_VALUE
    )
    mask &= ~invalid_roms_point

    out = df.loc[mask].copy()
    out.attrs["obs_col"] = obs_col
    out.attrs["mod_col"] = mod_col
    return out


def summarize_by_depth(
    df: pd.DataFrame,
    obs_col: str,
    mod_col: str,
    expected_depths: np.ndarray,
) -> pd.DataFrame:
    rows = []

    present_depths = np.sort(df["roms_depth"].dropna().unique())
    depths = np.unique(np.concatenate([expected_depths, present_depths]))

    for depth in depths:
        g = df[np.isclose(df["roms_depth"].values, depth, atol=1e-6)]

        stats = compute_stats(g[obs_col].values, g[mod_col].values)

        if len(g):
            mean_dz = float(np.nanmean(g["depth_difference"].values))
            max_dz = float(np.nanmax(g["depth_difference"].values))
            mean_wod_depth = float(np.nanmean(g["wod_depth"].values))
        else:
            mean_dz = np.nan
            max_dz = np.nan
            mean_wod_depth = np.nan

        rows.append(
            {
                "roms_depth": float(depth),
                "mean_wod_depth": mean_wod_depth,
                "mean_depth_difference": mean_dz,
                "max_depth_difference": max_dz,
                **stats,
            }
        )

    return pd.DataFrame(rows)


def print_summary(label: str, stats_df: pd.DataFrame):
    print(f"\n=== {label} ===")
    print(
        f"{'Depth(m)':>9} {'N':>7} {'Bias':>10} {'RMSE':>10} "
        f"{'MAE':>10} {'Corr':>9} {'R2':>9} {'mean|dz|':>10}"
    )

    for _, row in stats_df.iterrows():
        print(
            f"{row['roms_depth']:9.0f} "
            f"{int(row['N']):7d} "
            f"{row['bias']:10.4f} "
            f"{row['rmse']:10.4f} "
            f"{row['mae']:10.4f} "
            f"{row['corr']:9.4f} "
            f"{row['r2']:9.4f} "
            f"{row['mean_depth_difference']:10.3f}"
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "input_dir",
        type=str,
        help="Folder containing roms2wod_depthmatch_*.nc files",
    )
    ap.add_argument(
        "out_dir",
        type=str,
        help="Output folder for figures and CSV summaries",
    )
    ap.add_argument(
        "--roms_glob",
        type=str,
        default="roms2wod_depthmatch_*.nc",
        help="Glob for depth-matched files",
    )
    ap.add_argument(
        "--years",
        type=int,
        nargs="*",
        default=None,
        help="Optional WOD years to include, e.g. --years 1995 1996 1997",
    )
    ap.add_argument("--start", help="First hindcast day, YYYYMMDD (inclusive)")
    ap.add_argument("--end", help="Last hindcast day, YYYYMMDD (inclusive)")
    ap.add_argument(
        "--qc_max",
        type=float,
        default=0.0,
        help="Maximum accepted WOD flag. Default 0 preserves the previous flag <= 0 rule.",
    )
    ap.add_argument(
        "--teos10",
        action="store_true",
        help=(
            "Compare ROMS in-situ temperature (roms_temp_insitu) vs WOD "
            "temperature, and ROMS/WOD Absolute Salinity (roms_sa/wod_sa) "
            "instead of the raw potential temperature / practical salinity "
            "fields. Requires depth-matched files produced by the patched "
            "match_roms2wod_depths.py."
        ),
    )
    args = ap.parse_args()

    if (args.start is None) != (args.end is None):
        ap.error("--start and --end must be supplied together.")
    if args.start is None:
        start_time = end_time = None
    else:
        try:
            start_time = pd.to_datetime(args.start, format="%Y%m%d", errors="raise")
            end_date = pd.to_datetime(args.end, format="%Y%m%d", errors="raise")
        except ValueError as exc:
            ap.error(str(exc))
        if start_time > end_date:
            ap.error("--start must be earlier than or equal to --end.")
        end_time = end_date + pd.Timedelta(days=1)

    input_dir = Path(args.input_dir).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    selected_years = set(args.years) if args.years else None

    df = load_all_matches(
        input_dir=input_dir,
        roms_glob=args.roms_glob,
        selected_years=selected_years,
        start_time=start_time,
        end_time=end_time,
    )

    # Save everything before QC for traceability.
    df.to_csv(out_dir / "all_depthmatched_pairs_before_qc.csv", index=False)

    temp_df = make_qc_table(df, "temp", qc_max=args.qc_max, teos10=args.teos10)
    salt_df = make_qc_table(df, "salt", qc_max=args.qc_max, teos10=args.teos10)

    temp_obs_col, temp_mod_col = temp_df.attrs["obs_col"], temp_df.attrs["mod_col"]
    salt_obs_col, salt_mod_col = salt_df.attrs["obs_col"], salt_df.attrs["mod_col"]

    temp_df.to_csv(out_dir / "temperature_pairs_qc_pass.csv", index=False)
    salt_df.to_csv(out_dir / "salinity_pairs_qc_pass.csv", index=False)

    print(f"\nAll matched records read: {len(df)}")
    print(f"Temperature QC-passed pairs: {len(temp_df)} ({temp_obs_col} vs {temp_mod_col})")
    print(f"Salinity QC-passed pairs: {len(salt_df)} ({salt_obs_col} vs {salt_mod_col})")

    temp_stats = summarize_by_depth(
        temp_df,
        obs_col=temp_obs_col,
        mod_col=temp_mod_col,
        expected_depths=DEFAULT_ROMS_DEPTHS,
    )
    salt_stats = summarize_by_depth(
        salt_df,
        obs_col=salt_obs_col,
        mod_col=salt_mod_col,
        expected_depths=DEFAULT_ROMS_DEPTHS,
    )

    temp_stats.to_csv(out_dir / "temperature_statistics_by_depth.csv", index=False)
    salt_stats.to_csv(out_dir / "salinity_statistics_by_depth.csv", index=False)

    print_summary("TEMPERATURE", temp_stats)
    print_summary("SALINITY", salt_stats)

    # ------------------------------------------------------------------
    # One scatter plot for every fixed depth.
    # ------------------------------------------------------------------
    temp_plot_dir = out_dir / "temperature_by_depth"
    salt_plot_dir = out_dir / "salinity_by_depth"
    temp_plot_dir.mkdir(parents=True, exist_ok=True)
    salt_plot_dir.mkdir(parents=True, exist_ok=True)

    all_depths = np.unique(
        np.concatenate(
            [
                DEFAULT_ROMS_DEPTHS,
                temp_df["roms_depth"].dropna().unique(),
                salt_df["roms_depth"].dropna().unique(),
            ]
        )
    )

    for depth in np.sort(all_depths):
        td = temp_df[np.isclose(temp_df["roms_depth"].values, depth, atol=1e-6)]
        if not td.empty:
            save_depth_scatter(
                td,
                obs_col=temp_obs_col,
                mod_col=temp_mod_col,
                variable_label="Temperature",
                units="°C",
                depth=float(depth),
                out_dir=temp_plot_dir,
                fallback_limits=(0.0, 32.0),
            )

        sd = salt_df[np.isclose(salt_df["roms_depth"].values, depth, atol=1e-6)]
        if not sd.empty:
            save_depth_scatter(
                sd,
                obs_col=salt_obs_col,
                mod_col=salt_mod_col,
                variable_label="Salinity",
                units="g/kg" if args.teos10 else "",
                depth=float(depth),
                out_dir=salt_plot_dir,
                fallback_limits=(32.0, 37.5),
            )

    # ------------------------------------------------------------------
    # Combined all-depth plots.
    # ------------------------------------------------------------------
    if not temp_df.empty:
        save_all_depth_scatter(
            temp_df,
            obs_col=temp_obs_col,
            mod_col=temp_mod_col,
            variable_label="Temperature",
            units="°C",
            out_dir=out_dir,
            fallback_limits=(0.0, 32.0),
        )

    if not salt_df.empty:
        save_all_depth_scatter(
            salt_df,
            obs_col=salt_obs_col,
            mod_col=salt_mod_col,
            variable_label="Salinity",
            units="g/kg" if args.teos10 else "",
            out_dir=out_dir,
            fallback_limits=(32.0, 37.5),
        )

    # ------------------------------------------------------------------
    # Mean profiles and selected skill-vs-depth figures.
    # ------------------------------------------------------------------
    save_mean_profile(temp_stats, "Temperature", "°C", out_dir)
    save_mean_profile(salt_stats, "Salinity", "", out_dir)

    save_metric_vs_depth(temp_stats, "bias", "Temperature", "Bias (°C)", out_dir)
    save_metric_vs_depth(temp_stats, "rmse", "Temperature", "RMSE (°C)", out_dir)
    save_metric_vs_depth(temp_stats, "corr", "Temperature", "Correlation", out_dir)

    save_metric_vs_depth(salt_stats, "bias", "Salinity", "Bias", out_dir)
    save_metric_vs_depth(salt_stats, "rmse", "Salinity", "RMSE", out_dir)
    save_metric_vs_depth(salt_stats, "corr", "Salinity", "Correlation", out_dir)

    print("\nFinished.")
    print(f"Outputs written to: {out_dir}")
    print("Main statistics:")
    print(f"  {out_dir / 'temperature_statistics_by_depth.csv'}")
    print(f"  {out_dir / 'salinity_statistics_by_depth.csv'}")


if __name__ == "__main__":
    main()
