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

- The shared WOD input defaults to
  `/scratch/cawohdcst/data/hindcast_comparison/WOD_comparison/1995_2014/ocldb1786200299.1695566_CTD.nc`.
  Set `IHT_WOD_FILE` before running the launcher to use another WOD file.
- ROMS input is resolved from the active Inacawo-IHT environment:
  `$CAWO_POST/ocean3d` (normally `$SCRATCH/inacawo-iht/cawo_post/ocean3d`).
  For dated runs, files are first searched only in the corresponding
  `fYYYYMMDD` daily folders; their `TSTEP` values are then checked against the
  requested date range. If no matching daily folders contain NetCDF files,
  the extractor falls back to searching the full ROMS directory.
  If the nearest ROMS grid cell contains only fill values, the extractor
  checks its immediate neighbors and uses the nearest valid profile. The
  selected ROMS coordinate and its distance from the WOD cast are logged and
  stored in the output metadata.
- Results are written under
  `$CAWO_HINDCAST_BASE/validation/wod_comparison/<start>_<end>/jobs/<job-id>_<restart>/`,
  with separate `roms_extracted`, `roms_wod_depthmatched`, and
  `comparison_depthmatched` directories. Every Slurm attempt gets fresh output
  directories, so files from an earlier or failed attempt cannot be mixed into
  the new comparison. Earlier attempts are retained. Launcher and Slurm logs
  are under the date-range directory's `logs/`.
  The launcher prints the submitted job ID and the log paths. Follow progress
  with `tail -f` on `wod_comparison_<job-id>.log`; errors are written to
  `wod_comparison_<job-id>.err`. Each launcher and Slurm stage logs its start,
  end, result, and elapsed time. At exit, each log includes a duration summary
  for its stages and its total runtime. The Slurm total is compute-job runtime
  after the job starts; it does not include time waiting in the queue.

The Python stage scripts require their input and output paths as command-line
arguments. This avoids accidentally using stale per-user paths when a stage is
run manually; the launcher supplies paths from the active environment. For
each submitted job, final and intermediate products are under its
`jobs/<job-id>_<restart>/` folder.

The job runs the three stages in order: extract ROMS profiles at WOD cast
locations/times, match ROMS and WOD depths within 5 m (without vertical
interpolation), then apply WOD QC and produce CSV statistics and plots.
The `hindcast` Conda environment activated by `setup_env.bash` must include
the dependencies used by the scripts (`numpy`, `pandas`, `xarray`, `gsw`,
`matplotlib`, and `scikit-learn`).
