# WRF–ERA5 comparison

Run the four-variable time-series extraction from the InaCAWO-IHT environment:

```bash
./slurm_save_wrf_era5_series_array_clean.bash --start YYYYMMDD --end YYYYMMDD
```

Both dates are inclusive simulation-day labels. The command submits a four-task
SLURM array for mean sea-level pressure, 10-m eastward and northward wind, and
2-m relative humidity. For example:

```bash
./slurm_save_wrf_era5_series_array_clean.bash --start 20210404 --end 20210410
```

The launcher uses the `DEV1` partition by default. Set `IHT_SLURM_PARTITION`
to another partition if needed.

The script sources `$HOME/inacawo-iht/setup_env.bash` and reads postprocessed
WRF data from `$CAWO_POST/wrf2d/`, as defined by the IHT postprocess workflow.
It expects the daily WRF files under that product tree to match
`fYYYYMMDD/inacawo_hindcast_wrf2d_YYYY-*.nc`.

ERA5 and regridding-weight locations remain the shared paths configured in the
launcher:

- ERA5: `/scratch/cawohdcst/data/era5/`
- Bilinear weights: `/scratch/cawohdcst/data/postprocessed/weights_era5_to_wrf_bilinear.nc`

The four compressed NetCDF files and SLURM logs are written under this
directory:

- `output/pressure_YYYYMMDD_YYYYMMDD.nc`
- `output/u10_YYYYMMDD_YYYYMMDD.nc`
- `output/v10_YYYYMMDD_YYYYMMDD.nc`
- `output/rh2_YYYYMMDD_YYYYMMDD.nc`
- `logs/wrf_era5_ts_<job-id>_<array-task-id>.out` and `.err`

After all four extraction jobs complete, drift analysis can be run separately:

```bash
python wrf_era5_drift_analysis.py \
  --pressure output/pressure_YYYYMMDD_YYYYMMDD.nc \
  --rh2 output/rh2_YYYYMMDD_YYYYMMDD.nc \
  --u10 output/u10_YYYYMMDD_YYYYMMDD.nc \
  --v10 output/v10_YYYYMMDD_YYYYMMDD.nc \
  --outdir output/drift_analysis
```

The analysis writes CSV summaries and figures into the selected output
directory. Run the commands from an environment with the packages used by the
scripts installed; the extraction launcher activates the IHT environment.
