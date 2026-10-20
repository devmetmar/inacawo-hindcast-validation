# GDP comparison

This workflow compares drogued Global Drifter Program (GDP) observations with
surface-layer currents from the postprocessed ROMS `ocean3d` product.

## Run

From a shell with the Inacawo-IHT environment available:

```bash
cd /path/to/GDP_comparison
chmod +x run_gdp_comparison.bash
./run_gdp_comparison.bash --start YYYYMMDD --end YYYYMMDD
```

Both dates are inclusive and must be valid calendar dates in `YYYYMMDD` format.
For example:

```bash
./run_gdp_comparison.bash --start 20120101 --end 20121231
```

The launcher sources `$HOME/inacawo-iht/setup_env.bash`, then runs the
extraction and comparison scripts sequentially in the current shell. It does
not submit a Slurm job. The legacy `slurm_extract_roms.bash` file is not used
by this entrypoint.

## Data paths and matching

- GDP input files are expected at
  `/scratch/cawohdcst/data/hindcast_comparison/GDP_comparison/YYYY/drifter_6h_YYYY.nc`,
  with one file for every year covered by the requested date range.
- Postprocessed ROMS data is read from `$CAWO_POST/ocean3d`, as set by the
  Inacawo-IHT setup script. Files are searched recursively under the
  `fYYYYMMDD/` directories.
- ROMS eastward and northward currents are sampled at the nearest grid point
  and at the available `LAY` level closest to `-10 m`. Each GDP observation is
  matched to the nearest model time within 12 hours.
- The comparison uses observations while the drifter is drogued. A missing
  drogue-loss date is treated as no documented drogue loss.

## Outputs

GDP input files are read from
`/scratch/cawohdcst/data/hindcast_comparison/GDP_comparison/`. Results are
written under `$HOME/inacawo-hindcast-validation/GDP_comparison/`:

- Extracted GDP records with ROMS currents:
  `extracted/YYYYMMDD-YYYYMMDD/YYYY/gdp_roms_uv10m_<drifter-id>.nc`
- Comparison figures:
  `comparison_plots/YYYYMMDD-YYYYMMDD/YYYY/` and
  `comparison_plots/YYYYMMDD-YYYYMMDD/ALL/`

Each year folder and the `ALL` folder contain the zonal/meridional time series,
speed PDF, CDF and QQ plots, and direction distribution and difference plots.
The comparison script also prints sample counts and velocity bias, RMSE, and
correlation statistics to the console.

The environment loaded by `setup_env.bash` must provide the Python packages
used by the scripts, including `numpy`, `pandas`, `xarray`, `matplotlib`, and
`scipy`.
