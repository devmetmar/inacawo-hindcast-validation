# WOD comparison

This workflow compares WOD CTD casts with the postprocessed ROMS `ocean3d`
product from an Inacawo-IHT hindcast.

## Run

From a Slurm login node where Inacawo-IHT has been installed:

```bash
cd /path/to/WOD_comparison
chmod +x run_wod_comparison.bash
./run_wod_comparison.bash --start YYYYMMDD --end YYYYMMDD
```

The date range is inclusive and uses the same completed hindcast day labels as
`run_postprocess.bash`. The entrypoint sources
`$HOME/inacawo-iht/setup_env.bash`, checks that inputs exist, then submits one
Slurm job. `IHT_SETUP_ENV` can override the setup script location and
`IHT_SLURM_PARTITION` can override the default partition (`DEV1`).

## Data paths

- WOD input remains fixed at
  `/home/cawohdcst/WOD_comparison/1995_2014/ocldb1786200299.1695566_CTD.nc`.
- ROMS input is resolved from the active Inacawo-IHT environment:
  `$CAWO_POST/ocean3d` (normally `$SCRATCH/inacawo-iht/cawo_post/ocean3d`).
  Files are discovered recursively and their `TSTEP` values are restricted to
  the requested date range.
- Results are written under
  `$CAWO_HINDCAST_BASE/wod_comparison/<start>_<end>/`, with separate
  `roms_extracted`, `roms_wod_depthmatched`, and `comparison_depthmatched`
  directories. The Slurm log is under that run directory's `logs/`.

The job runs the three stages in order: extract ROMS profiles at WOD cast
locations/times, match ROMS and WOD depths within 5 m (without vertical
interpolation), then apply WOD QC and produce CSV statistics and plots.
The `hindcast` Conda environment activated by `setup_env.bash` must include
the dependencies used by the scripts (`numpy`, `pandas`, `xarray`, `gsw`,
`matplotlib`, and `scikit-learn`).
