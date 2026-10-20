# WRF–ERA5 comparison

Run the four-variable time-series extraction from the InaCAWO-IHT environment:

```bash
cd /path/to/WRF_ERA5_comparison
chmod +x run_wrf_comparison.bash
./run_wrf_comparison.bash --start YYYYMMDD --end YYYYMMDD
```

Both dates are inclusive simulation-day labels. The command submits a four-task
SLURM array for mean sea-level pressure, 10-m eastward and northward wind, and
2-m relative humidity. After extraction succeeds, it runs drift analysis and
waits until the complete workflow has finished. For example:

```bash
./run_wrf_comparison.bash --start 20210404 --end 20210410
```

The launcher sources `${WORK_BASE:-$HOME/inacawo-iht}/setup_env.bash`, so
`WORK_BASE`, `CAWO_POST`, and `CAWO_HINDCAST_BASE` come from the InaCAWO-IHT
environment rather than being tied to this checkout or a particular user.
Postprocessed WRF input is read from `$CAWO_POST/wrf2d/`; the expected files are
under `fYYYYMMDD/inacawo_hindcast_wrf2d_YYYY-*.nc`. Extraction opens WRF files
only from days in the requested date range, rather than scanning every file in
each calendar year, and limits ERA5 records to the same requested date/time
range by selecting only ERA5 day folders in that range before opening GRIB
files. WRF files are also reduced to the requested variable and its time/grid
coordinates while they are opened.

ERA5 and the bilinear regridding weights retain the existing shared-source
locations by default:

- ERA5: `/scratch/cawohdcst/data/era5/`
- Bilinear weights: `/scratch/cawohdcst/data/postprocessed/weights_era5_to_wrf_bilinear.nc`

For a different server where the shared files are mounted elsewhere, set
`WRF_ERA5_ERA5_ROOT` and/or `WRF_ERA5_WEIGHTS_FILE` before launching. The
defaults above remain unchanged. The SLURM partition defaults to `DEV1`; set
`IHT_SLURM_PARTITION` to override it.

Each invocation gets a unique run directory under
`$CAWO_HINDCAST_BASE/validation/wrf_era5_comparison/<start>_<end>/`, so a rerun
does not overwrite the previous run. Its contents are:

- `output/pressure_YYYYMMDD_YYYYMMDD.nc`
- `output/u10_YYYYMMDD_YYYYMMDD.nc`
- `output/v10_YYYYMMDD_YYYYMMDD.nc`
- `output/rh2_YYYYMMDD_YYYYMMDD.nc`
- `output/drift_analysis/qc_summary.csv`
- `output/drift_analysis/annual_stats_by_variable.csv`
- `output/drift_analysis/drift_trend_table.csv`
- `output/drift_analysis/fig1_overview_monthly_wrf_vs_era5.png`
- `output/drift_analysis/fig2_difference_smoothed.png`
- `output/drift_analysis/fig3_annual_stats_trend.png`
- `output/drift_analysis/fig4_qc_flagged_records.png`
- `output/drift_analysis/fig5_seasonal_bias_period_halves.png`
- `logs/wrf_era5_ts_<job-id>_<array-task-id>.out` and `.err`
- `logs/launcher.log`

Each SLURM task log ends with that variable's elapsed time and exit status.
`launcher.log` records the array elapsed time (including queue time) and the
drift-analysis elapsed time and end-to-end elapsed time. For task resource settings, the array worker is
`slurm_save_wrf_era5_series_array_clean.bash`; use `run_wrf_comparison.bash`
as the user-facing entrypoint. If the array fails, the launcher prints the
available task-log tails to the terminal; full logs remain in the run's
`logs/` directory. The launcher passes its source directory to each SLURM
task, so the Python drivers are found even when SLURM stages the worker script
under a temporary spool directory.

The launcher now runs the drift analysis automatically after extraction. To
rerun the analysis alone, point its inputs at the `output/` directory in the
run directory:

```bash
python wrf_era5_drift_analysis.py \
  --pressure "$RUN_DIR/output/pressure_YYYYMMDD_YYYYMMDD.nc" \
  --rh2 "$RUN_DIR/output/rh2_YYYYMMDD_YYYYMMDD.nc" \
  --u10 "$RUN_DIR/output/u10_YYYYMMDD_YYYYMMDD.nc" \
  --v10 "$RUN_DIR/output/v10_YYYYMMDD_YYYYMMDD.nc" \
  --outdir "$RUN_DIR/output/drift_analysis"
```

Replace `$RUN_DIR` with the actual `run_<timestamp>_<pid>` directory printed
by the launcher. The analysis writes CSV summaries and figures into the
selected output directory, prints elapsed time for each analysis stage and the
total analysis time, and uses the actual date span in its plots. Run the
analysis from the active IHT environment (or another Python environment with
the required packages). If `--outdir` is omitted, it defaults to
`$CAWO_HINDCAST_BASE/validation/wrf_era5_comparison/drift_analysis`; source
`${WORK_BASE:-$HOME/inacawo-iht}/setup_env.bash` first so that variable is set.
