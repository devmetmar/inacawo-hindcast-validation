#!/usr/bin/env python3
"""
Run DRF (GDP) vs ROMS comparison plots using DROGUED GDP observations only.

Folder layout expected:
  BASE_DIR/
    1995/
      gdp*
    1996/
      gdp*
    ...
(or any 4-digit year directories)

Outputs:
  OUT_DIR/
    YYYY/
      uv_series_YYYY.png
      speed_pdf_YYYY.png
      speed_cdf_YYYY.png
      speed_qq_YYYY.png
      dir_dist_YYYY.png
      dir_diff_YYYY.png
    ALL/
      uv_series_ALL.png
      speed_pdf_ALL.png
      speed_cdf_ALL.png
      speed_qq_ALL.png
      dir_dist_ALL.png
      dir_diff_ALL.png

Notes:
- This script is adapted from your original drf_comparison_.py.�
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np
import xarray as xr
import matplotlib
matplotlib.use("Agg")  # save-only backend (safe on servers / Spyder)
import matplotlib.pyplot as plt

from scipy.stats import pearsonr, ks_2samp, wasserstein_distance


# -------------------------
# Helpers from your script
# -------------------------
def clean_pairs(ve, vn, u_roms, v_roms):
    m = np.isfinite(ve) & np.isfinite(vn) & np.isfinite(u_roms) & np.isfinite(v_roms)
    return ve[m], vn[m], u_roms[m], v_roms[m]


def uv_to_speed_dir(u, v):
    spd = np.hypot(u, v)
    # heading TOWARD which current flows, [0, 360)
    ang = (np.degrees(np.arctan2(v, u)) + 360.0) % 360.0
    return spd, ang


def pdf_1d(x, bins):
    hist, edges = np.histogram(x, bins=bins, density=True)
    xc = 0.5 * (edges[:-1] + edges[1:])
    return xc, hist


def smooth(y, k=5):
    # simple moving-average smoother (odd k)
    k = max(1, int(k))
    k += (k + 1) % 2
    w = np.ones(k) / k
    return np.convolve(y, w, mode="same")


def overlap_coeff(p, q, dx):
    # ∫ min(p, q) dx  (1 = identical distributions)
    return np.sum(np.minimum(p, q)) * dx


# -------------------------
# Plot functions (SAVE)
# -------------------------
def plot_uv_series(ve, vn, u_roms, v_roms, title: str, out_png: Path):
    """Simple 2-panel u/v time series plot (index = sample number)."""
    fig, axs = plt.subplots(2, 1, figsize=(10, 6), sharex=True)

    axs[0].plot(ve, label="GDP", linewidth=0.8)
    axs[0].plot(u_roms, label="Hindcast", linewidth=0.8)
    axs[0].set_ylabel("Zonal velocity (m/s)")
    axs[0].grid(True, alpha=0.3)
    axs[0].legend()

    axs[1].plot(vn, label="GDP", linewidth=0.8)
    axs[1].plot(v_roms, label="Hindcast", linewidth=0.8)
    axs[1].set_ylabel("Meridional velocity (m/s)")
    axs[1].set_xlabel("Sample index")
    axs[1].grid(True, alpha=0.3)
    axs[1].legend()

    fig.suptitle(title, y=0.98)
    fig.tight_layout()
    fig.savefig(out_png, dpi=200)
    plt.close(fig)


def plot_speed_distributions(spd_obs, spd_mod, title_prefix: str, out_prefix: Path, nbins=40):
    """Save: speed PDF, speed CDF, speed QQ."""
    vmax = np.nanpercentile(np.hstack([spd_obs, spd_mod]), 99)
    if not np.isfinite(vmax) or vmax <= 0:
        vmax = np.nanmax(np.hstack([spd_obs, spd_mod]))
    bins = np.linspace(0, vmax, nbins + 1)

    # PDF
    xc_o, pdf_o = pdf_1d(spd_obs, bins)
    xc_m, pdf_m = pdf_1d(spd_mod, bins)
    dx = xc_o[1] - xc_o[0] if len(xc_o) > 1 else 1.0
    ovlp = overlap_coeff(pdf_o, pdf_m, dx)
    ks = ks_2samp(spd_obs, spd_mod, alternative="two-sided", mode="auto")
    wdist = wasserstein_distance(spd_obs, spd_mod)

    fig, ax = plt.subplots(1, 1, figsize=(7, 4))
    ax.plot(xc_o, smooth(pdf_o, 5), label="Obs PDF")
    ax.plot(xc_m, smooth(pdf_m, 5), label="Model PDF")
    ax.set_xlabel("Speed (m/s)")
    ax.set_ylabel("PDF")
    ax.grid(True, ls=":", alpha=0.5)
    ax.set_title(f"{title_prefix} | Speed PDF (overlap={ovlp:.2f}, KS D={ks.statistic:.2f}, W={wdist:.3f})")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_prefix.with_name(out_prefix.name + "_speed_pdf.png"), dpi=200)
    plt.close(fig)

    # CDF
    so = np.sort(spd_obs[np.isfinite(spd_obs)])
    sm = np.sort(spd_mod[np.isfinite(spd_mod)])
    F_o = np.linspace(0, 1, len(so), endpoint=False) if len(so) else np.array([])
    F_m = np.linspace(0, 1, len(sm), endpoint=False) if len(sm) else np.array([])

    fig, ax = plt.subplots(1, 1, figsize=(7, 4))
    if len(so):
        ax.plot(so, F_o, lw=2, label="Obs CDF")
    if len(sm):
        ax.plot(sm, F_m, lw=2, label="Model CDF")
    ax.set_xlabel("Speed (m/s)")
    ax.set_ylabel("CDF")
    ax.grid(True, ls=":", alpha=0.5)
    ax.set_title(f"{title_prefix} | Speed CDF")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_prefix.with_name(out_prefix.name + "_speed_cdf.png"), dpi=200)
    plt.close(fig)

    # Q-Q
    if len(so) and len(sm):
        q = np.linspace(0.01, 0.99, 99)
        qo = np.quantile(so, q)
        qm = np.quantile(sm, q)

        fig, ax = plt.subplots(1, 1, figsize=(5.5, 5.5))
        ax.scatter(qo, qm, s=12, alpha=0.7)
        lim = np.nanpercentile(np.hstack([qo, qm]), 99)
        ax.plot([0, lim], [0, lim], lw=2, linestyle="--")
        ax.set_xlim(0, lim)
        ax.set_ylim(0, lim)
        ax.set_xlabel("Obs speed quantiles")
        ax.set_ylabel("Model speed quantiles")
        ax.set_title(f"{title_prefix} | Speed Q–Q (1:1 line)")
        ax.grid(True, ls=":", alpha=0.5)
        fig.tight_layout()
        fig.savefig(out_prefix.with_name(out_prefix.name + "_speed_qq.png"), dpi=200)
        plt.close(fig)


def plot_direction_distributions(dir_obs_deg, dir_mod_deg, title_prefix: str, out_prefix: Path, nbin=72):
    """Save: direction distribution, and distribution difference curve."""
    o = dir_obs_deg % 360.0
    m = dir_mod_deg % 360.0

    edges = np.linspace(0, 360, nbin + 1)
    xc = 0.5 * (edges[:-1] + edges[1:])
    do, _ = np.histogram(o, bins=edges, density=True)
    dm, _ = np.histogram(m, bins=edges, density=True)
    dx = xc[1] - xc[0] if len(xc) > 1 else 5.0

    def circ_stats(theta_deg):
        th = np.deg2rad(theta_deg)
        C = np.nanmean(np.cos(th))
        S = np.nanmean(np.sin(th))
        mean_dir = (np.degrees(np.arctan2(S, C)) + 360.0) % 360.0
        R = np.hypot(C, S)  # mean resultant length [0..1]
        return mean_dir, R

    mu_o, R_o = circ_stats(o)
    mu_m, R_m = circ_stats(m)

    # np.histogram(..., density=True) uses direction bins in degrees, so
    # the densities are in 1/degree. Integrate using dx in degrees.
    ovlp = overlap_coeff(do, dm, dx)

    fig, ax = plt.subplots(1, 1, figsize=(8, 3.8))
    ax.plot(xc, smooth(do, 5), label=f"Obs (μ={mu_o:.0f}°, R={R_o:.2f})")
    ax.plot(xc, smooth(dm, 5), label=f"Mod (μ={mu_m:.0f}°, R={R_m:.2f})")
    ax.set_xlim(0, 360)
    ax.set_xlabel("Direction (deg, toward)")
    ax.set_ylabel("Density")
    ax.set_xticks(np.arange(0, 361, 45))
    ax.grid(True, ls=":", alpha=0.5)
    ax.set_title(f"{title_prefix} | Direction distribution (overlap={ovlp:.2f})")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_prefix.with_name(out_prefix.name + "_dir_dist.png"), dpi=200)
    plt.close(fig)

    fig, ax = plt.subplots(1, 1, figsize=(8, 3.0))
    ax.fill_between(xc, do - dm, 0, where=(do - dm) >= 0, alpha=0.5, label="Obs > Mod")
    ax.fill_between(xc, do - dm, 0, where=(do - dm) < 0, alpha=0.5, label="Mod > Obs")
    ax.set_xlim(0, 360)
    ax.set_xlabel("Direction (deg)")
    ax.set_ylabel("Δ density (Obs−Mod)")
    ax.grid(True, ls=":", alpha=0.5)
    ax.legend()
    ax.set_title(f"{title_prefix} | Direction difference")
    fig.tight_layout()
    fig.savefig(out_prefix.with_name(out_prefix.name + "_dir_diff.png"), dpi=200)
    plt.close(fig)


# -------------------------
# Data loading / processing
# -------------------------
def load_year_dataset(year_dir: Path) -> xr.Dataset:
    files = sorted(year_dir.glob("gdp*"))
    if not files:
        raise FileNotFoundError(f"No files matching gdp* in {year_dir}")
    ds = xr.open_mfdataset(
        [str(f) for f in files],
        combine="nested",
        concat_dim="row",
        parallel=False,
    )
    return ds


def extract_arrays(ds: xr.Dataset):
    """Extract velocity pairs and keep only observations while the drifter is drogued.

    Observations are retained when either:
      1) no drogue-loss date is recorded, or
      2) the observation time is on/before the recorded drogue-loss date.

    The original ve >= -10 fill-value filter and finite-pair cleaning are also retained.
    """
    ve = ds["ve"].values
    vn = ds["vn"].values
    u_roms = ds["u_roms"].values
    v_roms = ds["v_roms"].values
    time = ds["time"].values
    drogue_lost_date = ds["drogue_lost_date"].values

    # Keep samples while the drifter is drogued.
    # Missing drogue_lost_date is treated as no documented drogue loss.
    drogued = np.isnat(drogue_lost_date) | (time <= drogue_lost_date)

    # Retain original basic fill-value screening.
    m = (ve >= -10) & drogued

    ve = ve[m]
    vn = vn[m]
    u_roms = u_roms[m]
    v_roms = v_roms[m]

    # Clean to finite model-observation pairs.
    ve, vn, u_roms, v_roms = clean_pairs(ve, vn, u_roms, v_roms)

    return ve, vn, u_roms, v_roms


def compute_stats(ve, vn, u_roms, v_roms):
    bias_u = float(np.nanmean(u_roms - ve)) if len(ve) else np.nan
    bias_v = float(np.nanmean(v_roms - vn)) if len(vn) else np.nan
    rmse = float(np.sqrt(np.nanmean((u_roms - ve) ** 2 + (v_roms - vn) ** 2))) if len(ve) else np.nan
    corr_u = float(pearsonr(u_roms, ve).statistic) if len(u_roms) else np.nan
    corr_v = float(pearsonr(v_roms, vn).statistic) if len(v_roms) else np.nan
    return bias_u, bias_v, rmse, corr_u, corr_v


def is_year_dir(p: Path) -> bool:
    return p.is_dir() and re.fullmatch(r"\d{4}", p.name) is not None


def run_one(label: str, ve, vn, u_roms, v_roms, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)

    bias_u, bias_v, rmse, corr_u, corr_v = compute_stats(ve, vn, u_roms, v_roms)
    n = len(ve)

    title = (
        f"{label} | N={n} | bias(u,v)=({bias_u:.3f},{bias_v:.3f}) | "
        f"RMSE={rmse:.3f} | corr(u,v)=({corr_u:.2f},{corr_v:.2f})"
    )

    plot_uv_series(
        ve, vn, u_roms, v_roms,
        title=title,
        out_png=out_dir / f"uv_series_{label}.png",
    )

    spd_obs, dir_obs = uv_to_speed_dir(ve, vn)
    spd_mod, dir_mod = uv_to_speed_dir(u_roms, v_roms)

    prefix = out_dir / f"{label}"
    plot_speed_distributions(spd_obs, spd_mod, title_prefix=label, out_prefix=prefix)
    plot_direction_distributions(dir_obs, dir_mod, title_prefix=label, out_prefix=prefix)

    print(
        f"[{label}] N={n} bias_u={bias_u:.3f} bias_v={bias_v:.3f} "
        f"RMSE={rmse:.3f} corr_u={corr_u:.2f} corr_v={corr_v:.2f}"
    )


def main():
    ap = argparse.ArgumentParser(description="Run DRF/GDP vs ROMS comparisons for each year and all years.")
    ap.add_argument("base_dir", type=str, help="Folder containing year subfolders (e.g., .../GDP_comparison)")
    ap.add_argument("out_dir", type=str, help="Where to save figures")
    ap.add_argument("--years", type=int, nargs="*", default=None, help="Optional list of years to process (e.g., 1998 1999 2000)")
    args = ap.parse_args()

    base_dir = Path(args.base_dir).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    year_dirs = sorted([p for p in base_dir.iterdir() if is_year_dir(p)])
    if args.years:
        year_set = {str(y) for y in args.years}
        year_dirs = [p for p in year_dirs if p.name in year_set]

    if not year_dirs:
        raise RuntimeError(f"No year directories found under {base_dir}")

    all_ve, all_vn, all_u, all_v = [], [], [], []

    for yd in year_dirs:
        year = yd.name
        print(f"=== Processing {year} ===")
        ds = load_year_dataset(yd)
        ve, vn, u_roms, v_roms = extract_arrays(ds)

        all_ve.append(ve)
        all_vn.append(vn)
        all_u.append(u_roms)
        all_v.append(v_roms)

        run_one(label=year, ve=ve, vn=vn, u_roms=u_roms, v_roms=v_roms, out_dir=out_dir / year)
        ds.close()

    print("=== Processing ALL years combined ===")
    ve = np.concatenate(all_ve) if all_ve else np.array([])
    vn = np.concatenate(all_vn) if all_vn else np.array([])
    u_roms = np.concatenate(all_u) if all_u else np.array([])
    v_roms = np.concatenate(all_v) if all_v else np.array([])

    run_one(label="ALL", ve=ve, vn=vn, u_roms=u_roms, v_roms=v_roms, out_dir=out_dir / "ALL")


if __name__ == "__main__":
    main()
