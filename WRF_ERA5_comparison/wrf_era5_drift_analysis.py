#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wrf_era5_drift_analysis.py

Purpose
-------
Given the per-variable NetCDF files produced by save_pressure_series_clean.py,
save_rh2_series_clean.py, save_u10_series_clean.py and save_v10_series_clean.py
(domain-mean WRF, ERA5-on-WRF-grid, and WRF-ERA5 difference time series, hourly,
1995-2014), this script checks whether the WRF solution drifted away from the
ERA5 boundary/forcing over the 20-year hindcast, and produces a set of
publication-style figures plus a CSV table of yearly statistics.

This is NOT an independent skill evaluation against observations. WRF is
forced by ERA5, so good agreement is expected; the question this script
answers is whether the *agreement itself* is stable through time (no trend
in bias/RMSE/correlation) or whether it degrades (drifts) as the run
progresses away from each restart/reinitialization.


Usage
-----
python wrf_era5_drift_analysis.py \
    --pressure pressure_1995_2014.nc \
    --rh2 rh2_1995_2014.nc \
    --u10 u10_1995_2014.nc \
    --v10 v10_1995_2014.nc \
    --outdir ./figures
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr
from scipy import stats

# ----------------------------------------------------------------------
# Variable metadata: display name, units, and a physically-plausible
# range used to flag corrupted/fill-value WRF records (NOT a QC of ERA5,
# which was not observed to contain bad records in this dataset).
# ----------------------------------------------------------------------
VARIABLES = {
    "pressure": dict(
        file_key="pressure",
        label="Mean sea-level pressure",
        short="MSLP",
        units="hPa",
        wrf_valid_range=(900.0, 1100.0),
    ),
    "rh2": dict(
        file_key="rh2",
        label="2-m relative humidity",
        short="RH2",
        units="%",
        wrf_valid_range=(1.0, 100.0),
    ),
    "u10": dict(
        file_key="u10",
        label="10-m eastward wind",
        short="U10",
        units="m s$^{-1}$",
        wrf_valid_range=(-60.0, 60.0),
    ),
    "v10": dict(
        file_key="v10",
        label="10-m northward wind",
        short="V10",
        units="m s$^{-1}$",
        wrf_valid_range=(-60.0, 60.0),
    ),
}

plt.rcParams.update(
    {
        "figure.dpi": 120,
        "savefig.dpi": 150,
        "savefig.bbox": "tight",
        "font.size": 11,
        "axes.grid": True,
        "grid.alpha": 0.3,
    }
)

COLOR_WRF = "tab:blue"
COLOR_ERA5 = "tab:orange"
COLOR_DIFF = "tab:green"


# ----------------------------------------------------------------------
# Loading and QC
# ----------------------------------------------------------------------
def load_series(path: str, key: str) -> pd.DataFrame:
    """Load one variable file into a tidy DataFrame with a QC flag column."""
    ds = xr.open_dataset(path)
    df = ds[["wrf", "era5", "difference"]].to_dataframe()[["wrf", "era5", "difference"]]
    df.index.name = "time"
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="first")]

    lo, hi = VARIABLES[key]["wrf_valid_range"]
    bad = (df["wrf"] < lo) | (df["wrf"] > hi) | df["wrf"].isna() | df["era5"].isna()
    df["flag_bad"] = bad
    ds.close()
    return df


def load_all(paths: dict) -> dict:
    """Load all variables and share the corrupted-record flag across them.

    The corrupted WRF records (exact 0.0 fill values) come from the same
    underlying WRF output file/timestep for a given hour, so a bad pressure
    or RH2 record at a given time implies the wind components at that same
    time are unreliable too, even though U10/V10 near zero is otherwise a
    perfectly physical value and can't be distinguished from a fill value
    on its own. The union of flagged timestamps from all variables with an
    unambiguous physical range (pressure, RH2) is therefore applied to
    every variable.
    """
    data = {key: load_series(path, key) for key, path in paths.items()}

    bad_times = pd.DatetimeIndex([])
    for key, df in data.items():
        bad_times = bad_times.union(df.index[df["flag_bad"]])

    for key, df in data.items():
        shared_bad = df.index.isin(bad_times)
        df["flag_bad"] = df["flag_bad"] | shared_bad

    return data


def qc_summary(data: dict) -> pd.DataFrame:
    """One row per variable: how many records were flagged and when."""
    rows = []
    for key, df in data.items():
        n_bad = int(df["flag_bad"].sum())
        years = sorted(df.index[df["flag_bad"]].year.unique().tolist()) if n_bad else []
        rows.append(
            {
                "variable": VARIABLES[key]["short"],
                "n_total": len(df),
                "n_flagged": n_bad,
                "pct_flagged": 100.0 * n_bad / len(df) if len(df) else np.nan,
                "years_affected": ", ".join(str(y) for y in years),
            }
        )
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------
# Statistics
# ----------------------------------------------------------------------
def annual_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Bias, RMSE and correlation per calendar year, on QC'd data only."""
    clean = df.loc[~df["flag_bad"]].copy()
    clean["year"] = clean.index.year

    def _agg(g):
        return pd.Series(
            {
                "bias": g["difference"].mean(),
                "rmse": np.sqrt((g["difference"] ** 2).mean()),
                "corr": g["wrf"].corr(g["era5"]),
                "n": len(g),
            }
        )

    out = clean.groupby("year").apply(_agg, include_groups=False)
    return out


def trend_test(years: np.ndarray, values: np.ndarray) -> dict:
    """Linear trend (OLS) of a yearly statistic against year, with p-value."""
    mask = np.isfinite(values)
    if mask.sum() < 3:
        return dict(slope=np.nan, intercept=np.nan, pvalue=np.nan, rvalue=np.nan)
    res = stats.linregress(years[mask], values[mask])
    return dict(slope=res.slope, intercept=res.intercept, pvalue=res.pvalue, rvalue=res.rvalue)


def build_summary_table(data: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (annual_stats_long, trend_table) across all variables."""
    annual_frames = []
    trend_rows = []
    for key, df in data.items():
        astats = annual_stats(df)
        astats["variable"] = VARIABLES[key]["short"]
        annual_frames.append(astats.reset_index())

        years = astats.index.values.astype(float)
        for metric in ("bias", "rmse", "corr"):
            t = trend_test(years, astats[metric].values)
            trend_rows.append(
                {
                    "variable": VARIABLES[key]["short"],
                    "metric": metric,
                    "slope_per_year": t["slope"],
                    "pvalue": t["pvalue"],
                    "r_of_trend": t["rvalue"],
                    "significant_at_0.05": (t["pvalue"] < 0.05) if np.isfinite(t["pvalue"]) else False,
                }
            )

    annual_long = pd.concat(annual_frames, ignore_index=True)
    trend_table = pd.DataFrame(trend_rows)
    return annual_long, trend_table


# ----------------------------------------------------------------------
# Figures
# ----------------------------------------------------------------------
def fig_overview_monthly(data: dict, outdir: Path) -> Path:
    """4-panel figure: monthly-mean WRF vs ERA5 over the full 20-year record."""
    fig, axes = plt.subplots(4, 1, figsize=(11, 12), sharex=True)
    for ax, key in zip(axes, VARIABLES):
        df = data[key].loc[~data[key]["flag_bad"]]
        monthly = df[["wrf", "era5"]].resample("MS").mean()
        ax.plot(monthly.index, monthly["wrf"], color=COLOR_WRF, lw=1.2, label="WRF")
        ax.plot(monthly.index, monthly["era5"], color=COLOR_ERA5, lw=1.2, ls="--", label="ERA5")
        meta = VARIABLES[key]
        ax.set_ylabel(f"{meta['short']} ({meta['units']})")
        ax.set_title(f"{meta['label']}: monthly-mean domain average, 1995-2014", fontsize=11, loc="left")
        ax.legend(loc="upper right", ncol=2, fontsize=9)
    axes[-1].set_xlabel("Year")
    fig.suptitle("WRF vs ERA5 domain-mean monthly series (QC'd)", y=1.01, fontsize=13)
    fig.tight_layout()
    path = outdir / "fig1_overview_monthly_wrf_vs_era5.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def fig_difference_smoothed(data: dict, outdir: Path) -> Path:
    """4-panel figure: WRF-ERA5 difference, daily mean + 365-day rolling mean, with zero line."""
    fig, axes = plt.subplots(4, 1, figsize=(11, 12), sharex=True)
    for ax, key in zip(axes, VARIABLES):
        df = data[key].loc[~data[key]["flag_bad"]]
        daily = df["difference"].resample("D").mean()
        annual_roll = daily.rolling(365, center=True, min_periods=180).mean()
        ax.plot(daily.index, daily, color=COLOR_DIFF, lw=0.4, alpha=0.35, label="Daily mean")
        ax.plot(annual_roll.index, annual_roll, color="k", lw=1.8, label="365-day rolling mean")
        ax.axhline(0, color="grey", lw=0.8)
        meta = VARIABLES[key]
        ax.set_ylabel(f"WRF-ERA5 ({meta['units']})")
        ax.set_title(f"{meta['label']}: bias evolution, 1995-2014", fontsize=11, loc="left")
        ax.legend(loc="upper right", ncol=2, fontsize=9)
    axes[-1].set_xlabel("Year")
    fig.suptitle("Daily-mean difference and long-term rolling mean (QC'd)", y=1.01, fontsize=13)
    fig.tight_layout()
    path = outdir / "fig2_difference_smoothed.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def fig_annual_stats_trend(annual_long: pd.DataFrame, trend_table: pd.DataFrame, outdir: Path) -> Path:
    """3 columns (bias, RMSE, corr) x 4 rows (variables), each with an OLS trend line and p-value."""
    metrics = [("bias", "Bias (WRF-ERA5)"), ("rmse", "RMSE"), ("corr", "Correlation")]
    keys = list(VARIABLES.keys())
    fig, axes = plt.subplots(len(keys), len(metrics), figsize=(13, 12), sharex=True)

    for i, key in enumerate(keys):
        short = VARIABLES[key]["short"]
        units = VARIABLES[key]["units"]
        sub = annual_long[annual_long["variable"] == short].sort_values("year")
        for j, (metric, mlabel) in enumerate(metrics):
            ax = axes[i, j]
            years = sub["year"].values.astype(float)
            vals = sub[metric].values
            ax.plot(years, vals, "o-", color="tab:blue", ms=4, lw=1.2)

            trow = trend_table[(trend_table["variable"] == short) & (trend_table["metric"] == metric)]
            if len(trow):
                slope = trow["slope_per_year"].values[0]
                pval = trow["pvalue"].values[0]
                intercept = trow.iloc[0].get("intercept", np.nan)
                yfit = np.polyval(
                    [slope, np.nanmean(vals) - slope * np.nanmean(years)], years
                )
                ax.plot(years, yfit, "--", color="tab:red", lw=1.3)
                sig = "significant" if (np.isfinite(pval) and pval < 0.05) else "n.s."
                ax.text(
                    0.02,
                    0.05,
                    f"slope={slope:+.3g}/yr\np={pval:.2f} ({sig})",
                    transform=ax.transAxes,
                    fontsize=8,
                    va="bottom",
                    color="tab:red",
                )
            if j == 0:
                ax.set_ylabel(f"{short}\n({units})", fontsize=9)
            if i == 0:
                ax.set_title(mlabel, fontsize=11)
            if i == len(keys) - 1:
                ax.set_xlabel("Year")
    fig.suptitle(
        "Annual bias / RMSE / correlation between WRF and ERA5, with linear trend (drift) test",
        y=1.01,
        fontsize=13,
    )
    fig.tight_layout()
    path = outdir / "fig3_annual_stats_trend.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def fig_qc_flags(data: dict, outdir: Path) -> Path:
    """Show where flagged (corrupted / fill-value) WRF records occur in time."""
    fig, ax = plt.subplots(figsize=(11, 3.5))
    for i, key in enumerate(VARIABLES):
        df = data[key]
        bad_times = df.index[df["flag_bad"]]
        ax.scatter(
            bad_times,
            np.full(len(bad_times), i),
            marker="|",
            s=200,
            color="tab:red",
        )
    ax.set_yticks(range(len(VARIABLES)))
    ax.set_yticklabels([VARIABLES[k]["short"] for k in VARIABLES])
    ax.set_ylim(-0.5, len(VARIABLES) - 0.5)
    ax.set_xlabel("Time")
    ax.set_title("Flagged WRF records excluded from statistics (fill-value / out-of-range)")
    fig.tight_layout()
    path = outdir / "fig4_qc_flagged_records.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def fig_seasonal_cycle_bias(data: dict, outdir: Path) -> Path:
    """Monthly-climatology bias, split into first-half vs second-half of record,
    to check whether the seasonal-cycle bias itself has drifted."""
    fig, axes = plt.subplots(2, 2, figsize=(11, 7))
    axes = axes.ravel()
    for ax, key in zip(axes, VARIABLES):
        df = data[key].loc[~data[key]["flag_bad"]].copy()
        mid_year = 2005
        first = df[df.index.year < mid_year]
        second = df[df.index.year >= mid_year]

        clim_first = first["difference"].groupby(first.index.month).mean()
        clim_second = second["difference"].groupby(second.index.month).mean()

        ax.plot(clim_first.index, clim_first.values, "o-", label="1995-2004", color="tab:blue")
        ax.plot(clim_second.index, clim_second.values, "o-", label="2005-2014", color="tab:orange")
        ax.axhline(0, color="grey", lw=0.8)
        meta = VARIABLES[key]
        ax.set_title(meta["label"], fontsize=10)
        ax.set_ylabel(f"WRF-ERA5 ({meta['units']})")
        ax.set_xlabel("Month")
        ax.set_xticks(range(1, 13))
        ax.legend(fontsize=8)
    fig.suptitle("Mean seasonal-cycle bias: first vs second decade", y=1.02, fontsize=13)
    fig.tight_layout()
    path = outdir / "fig5_seasonal_bias_decades.png"
    fig.savefig(path)
    plt.close(fig)
    return path


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--pressure", required=True)
    p.add_argument("--rh2", required=True)
    p.add_argument("--u10", required=True)
    p.add_argument("--v10", required=True)
    p.add_argument("--outdir", default="./figures")
    args = p.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    paths = dict(pressure=args.pressure, rh2=args.rh2, u10=args.u10, v10=args.v10)
    data = load_all(paths)

    qc = qc_summary(data)
    qc.to_csv(outdir / "qc_summary.csv", index=False)
    print("QC summary:")
    print(qc.to_string(index=False))

    annual_long, trend_table = build_summary_table(data)
    annual_long.to_csv(outdir / "annual_stats_by_variable.csv", index=False)
    trend_table.to_csv(outdir / "drift_trend_table.csv", index=False)
    print("\nDrift trend table (linear slope of yearly bias/RMSE/corr vs year):")
    print(trend_table.to_string(index=False))

    fig_overview_monthly(data, outdir)
    fig_difference_smoothed(data, outdir)
    fig_annual_stats_trend(annual_long, trend_table, outdir)
    fig_qc_flags(data, outdir)
    fig_seasonal_cycle_bias(data, outdir)

    print(f"\nFigures and tables written to: {outdir.resolve()}")


if __name__ == "__main__":
    main()
