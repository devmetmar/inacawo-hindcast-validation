# inacawo-src

Build helpers for the InaCAWO coupled model (COAWST: WRF–ROMS–SWAN, CAWO_3way)
used by the hindcast workflow (`MODEL_BASE=$HOME/inacawo-src`).

This repo holds **scripts and headers only**. The COAWST source is a tarball
on shared scratch, and every participant compiles their own `coawstM`.

| Directory | Repo | Content |
|---|---|---|
| `~/inacawo-deps` (+ `~/apps`) | [devmetmar/inacawo-deps](https://github.com/devmetmar/inacawo-deps) | libraries, `hindcast` conda env, LiveOcean, `COAWST_ENV` |
| `~/inacawo-src` | [devmetmar/inacawo-src](https://github.com/devmetmar/inacawo-src) | build scripts and headers only (this repo); you compile `binaries/{ramp_tides,no_ramp_tides}/coawstM` |
| `~/inacawo-iht` | [devmetmar/inacawo-iht](https://github.com/devmetmar/inacawo-iht) | hindcast working directory (preprocess / run / postprocess) |

## Layout

```
$HOME/inacawo-src/
  build_coawst.bash              # wrapper: extract source, set header, compile, install
  headers/
    cawo_3way_ramp_tides.h       # day 1           (# define RAMP_TIDES)
    cawo_3way_no_ramp_tides.h    # continuing days (# undef RAMP_TIDES)
  binaries/
    ramp_tides/coawstM           # + build_info.txt   (gitignored)
    no_ramp_tides/coawstM        # + build_info.txt   (gitignored)
  coawst_ramp_tides/             # extracted COAWST source tree per variant (gitignored,
  coawst_no_ramp_tides/          #   ~1.1 GB each after the build)
  logs/                          # build + SLURM logs (gitignored)

/scratch/cawohdcst_ft2/inacawo-iht/src_tarballs/   # shared, read-only for others
  inacawo_coawst_src.tar.gz      # cleaned COAWST source (~230 MB, ~540 MB unpacked)
  SHA256SUMS
```

## Ramp vs no-ramp

Each hindcast day is a separate COAWST run. The two headers differ only in
`RAMP_TIDES` (line 102):

| Variant | Used for | Effect |
|---|---|---|
| `ramp_tides` | first day (`copy_files_for_run_day1.bash`) | tidal forcing ramped up from zero (`TANH` over 1 day) |
| `no_ramp_tides` | continuing days (`copy_files_for_run.bash`) | full tidal forcing from the start (restart) |

All other CPP options are identical, and both variants come from the same
source tarball.

## Quick start (participants)

This is step 3 of the shared setup. Step 2 is the deps installer (libraries in
`~/apps`, then the conda env). `--offline` still installs those libraries; it
only skips conda downloads and uses the shared `hindcast` env:

```bash
bash ~/inacawo-deps/install_hindcast_env.bash             # online: private env
bash ~/inacawo-deps/install_hindcast_env.bash --offline   # shared env, no downloads
```

Do not `conda activate hindcast` for this build: `build_coawst.bash` sources
`inacawo-deps/env` and `COAWST_ENV` itself. After the binaries exist, daily
work is `source ~/inacawo-iht/setup_env.bash`. Other installer flags are in
the inacawo-deps README.

```bash
cd $HOME/inacawo-src
# IHT accounts: --partition DEV1. Omit it only if your account is allowed
# on HDCAST; otherwise the wrapper selects DEV1 itself.
bash build_coawst.bash --sbatch --partition DEV1   # 2 jobs, 1 node x 96 cores each
squeue -u $USER                                    # compile_cawo_ramp_tides / _no_ramp_tides
tail -f logs/compile_cawo_*_<jobid>.out

ls -la binaries/*/coawstM
cat binaries/*/build_info.txt
```

Each job (about 30 minutes, the two run in parallel):

1. Extracts the source tarball into `coawst_<variant>/` (sha256-checked) on
   first use, and points `WRF/configure.wrf` at your `~/apps` NetCDF/HDF5.
2. Copies the variant header and runs `coawst.bash` (WRF, ROMS, SWAN, MCT).
   WRF is most of the time.
3. Checks `coawstM`: the ROMS CPP list embedded in the binary must contain
   `RAMP_TIDES` for ramp and must not for no-ramp
   (`strings coawstM | grep RAMP_TIDES`).
4. Installs `binaries/<variant>/coawstM` plus `build_info.txt` (header and
   binary md5, source sha256, log path).

### Options

```bash
bash build_coawst.bash --sbatch --variant no_ramp_tides   # one variant only
bash build_coawst.bash --sbatch --time 02:00:00           # longer SLURM limit
bash build_coawst.bash --sbatch --partition DEV1          # IHT accounts (also the auto fallback)
bash build_coawst.bash --force-extract --sbatch           # fresh source trees
bash build_coawst.bash -j 16                              # run in current shell/job (sequential)
bash build_coawst.bash --help
```

Each `--sbatch` job uses `--nodes=1 --ntasks-per-node=96 --exclusive`,
default time limit `01:00:00`. IHT accounts pass `--partition DEV1` (or
`IHT_SLURM_PARTITION=DEV1`). If you omit it, the job selects `HDCAST` only
when your Slurm account is in that partition’s `AllowAccounts`; otherwise
`DEV1` (so the job does not sit in `PENDING (PartitionConfig)`). `make -j`
defaults to `$SLURM_NTASKS` (96); WRF's own build is capped at `-j 20`.

### Why it takes ~30 minutes, and why more nodes don't help

`make` runs on one node only, so extra nodes in the same job sit idle. Most of
the time goes to a few large WRF files that each compile serially for 5–10
minutes with `-O3 -ip` (`module_sf_clm`, `module_cumulus_driver`, `module_cpl`,
`module_comm_dm_4`); the rest is already spread over the cores. The original
`~/models` compile logs show the same per-file times. Sharing one tree between
the variants does not help either: `coawst.bash` re-runs the WRF registry, so
WRF is recompiled for every build. Building each variant in its own tree, as a
separate job, halves the wall time (2 nodes in total).

## Changing CPP options

Edit the header(s) in `headers/` and rebuild. Keep the two headers identical
except for `RAMP_TIDES`, and check with:

```bash
diff headers/cawo_3way_ramp_tides.h headers/cawo_3way_no_ramp_tides.h
```

The wrapper copies the selected header to
`coawst_<variant>/Projects/CAWO_3way/cawo_3way.h`, so do not edit that copy.

## Troubleshooting

- `COAWST model deps missing`: run `bash ~/inacawo-deps/install_hindcast_env.bash --only-coawst-deps`.
- `build failed`: read `logs/build_<variant>_<timestamp>.log`. The wrapper prints its last 30 lines.
- Job hits the time limit: resubmit with `--time 02:00:00`.
- Corrupted or partial tree: rebuild with `--force-extract`.
- Parallel builds must not share `$HOME/make_macros.mk`. ROMS writes that file and includes it while `make` is starting. `build_coawst.bash` points it at `coawst_<variant>/make_macros.mk` instead, so the two jobs keep their own copy.

## Maintainer: refresh the source tarball (as `cawohdcst_ft2`)

The tarball was made from
`~/models/cawo_3way_swell_mods_ramp_tides`. It excludes `Build/`, `WRF.orig/`,
`WRF_htr/`, `coawstM*`, logs, object files, other `Projects/`, and the
`coawst.bash.*`/`makefile.*` variants, and `WRF/./clean` was run on it (keeping
`configure.wrf`). Portability patches applied:

- `coawst.bash`: `MY_ROOT_DIR="${COAWST_SRC_DIR:?}"`, `NETCDF_CONFIG="${NC_CONFIG:?}"`
- `WRF/configure.wrf`: deps prefix replaced by `@INACAWO_DEPS_PREFIX@`
  (filled in by `build_coawst.bash`)
- `WRF/configure.wrf`: `FC = $(DM_FC)` instead of `FC = time $(DM_FC)`
  (compute nodes have no `/usr/bin/time`)
- `WRF/tools/gen_comms.c` removed: if a copy of the stub is present, WRF does
  not install the RSL_LITE version, and the build fails with empty
  `REGISTRY_COMM_*` includes (`module_comm_dm_*.f90 ... END-OF-FILE`)

The tarball's top directory must stay `coawst/`; the wrapper renames it to
`coawst_<variant>/` on extraction.

After repacking:

```bash
D=/scratch/cawohdcst_ft2/inacawo-iht/src_tarballs
(cd $D && sha256sum inacawo_coawst_src.tar.gz > SHA256SUMS)
chmod 755 $D && chmod 644 $D/*
```
