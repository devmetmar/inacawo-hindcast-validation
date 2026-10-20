# postprocess

Regrid hindcast history to the CAWO LL0.025 analysis grid with **xesmf**
(`hindcast` conda env). Code lives here under `$HOME/inacawo-iht/postprocess/`;
writable products go to **`$CAWO_POST`** (`$SCRATCH/inacawo-iht/cawo_post/`).

A shared multi-year archive (read-only) is also available at
`/scratch/cawohdcst/data/postprocessed` — see
[`tutorials/tutorial_postprocessed_hindcast.ipynb`](tutorials/tutorial_postprocessed_hindcast.ipynb).

## Entrypoint (preferred)

```bash
# From repo root or postprocess/:
./run_postprocess.bash --start YYYYMMDD --end YYYYMMDD
./run_postprocess.bash --start YYYYMMDD --end YYYYMMDD --stage roms2d
./run_postprocess.bash --start YYYYMMDD --end YYYYMMDD --stage wrf --dry-run
./run_postprocess.bash --help
```

`run_postprocess.bash` sources `setup_env.bash`, sets `IHT_START_DATE` /
`IHT_END_DATE` (and ISO/dot variants), derives the Slurm array from the date
span, and submits product scripts. **No end+1 padding** — dates are completed
hindcast day labels. Pass `--dry-run` to print commands only.

**SLURM wait by default:** each stage is submitted and monitored into the
postprocess SST log until COMPLETED. Terminal still prints only the log
realpath — monitor with `tail -f <logfile>`. Pass `--no-wait` to submit and exit.

**Partition:** auto-selects `HDCAST` if your Slurm account is allowed; otherwise
`DEV1`. Override with `--partition NAME` or `IHT_SLURM_PARTITION`.

**Auto-log (quiet):** full stdout/stderr go to
`$WORK_BASE/logs/postprocess/postprocess_<start>_<end>_<stage>_<timestamp>.log`.
Ctrl+C `scancel`s jobs from that run. Use `-v/--verbose` to mirror; `--no-log`
disables the log file.

| `--stage` (alias) | Expands to |
|-------------------|------------|
| `all` (default) | `roms2d,roms3d,wrf2d,wrf3d` |
| `roms` | `roms2d,roms3d` |
| `wrf` | `wrf2d,wrf3d` |

Atomic steps may be passed directly (e.g. `--stage roms2d`).

## Prerequisites

```bash
source $HOME/inacawo-iht/setup_env.bash
# model output under $CAWO_OUTPUT
```

| Var | Role |
|-----|------|
| `CAWO_OUTPUT` | Raw model output (`$CAWO_HINDCAST_BASE/cawo_output`) |
| `CAWO_POST` | Postprocessed products (`$CAWO_HINDCAST_BASE/cawo_post`) |

## Layout

```
postprocess/
  run_postprocess.bash    # entrypoint
  tutorials/              # Jupyter user + walkthrough notebook
  post_roms2d/            # ocean2d regrid + SLURM
  post_roms3d/            # ocean3d regrid + SLURM
  post_wrf2d/             # wrf2d regrid + SLURM
  post_wrf3d/             # wrf3d regrid + SLURM
```

| Subdir | Product under `$CAWO_POST` | Cadence |
|--------|----------------------------|---------|
| `post_roms2d/` | `ocean2d/` | HIS `1 4 7 … 25` (3-hourly) |
| `post_roms3d/` | `ocean3d/` | same HIS list |
| `post_wrf2d/` | `wrf2d/` | 3-hourly `wrfhtr` |
| `post_wrf3d/` | `wrf3d/` | 3-hourly `wrfplev` |

## Manual sbatch (fallback)

If not using the entrypoint, edit dates inside each script (or export
`IHT_START_DATE_ISO` / `IHT_END_DATE_ISO`) and submit from the product dir:

```bash
cd $WORK_BASE/postprocess/post_roms2d
sbatch slurm_run_post_roms2d.bash
```

See each subdirectory `README.md` for scripts and naming.
