# inacawo-deps

Pinned dependencies for the InaCAWO hindcast workflow (IHT / in-house training):

- **COAWST model deps** — prebuilt NetCDF, HDF5, MCT, … (Intel oneAPI 2021.5.1) → `$HOME/apps`
- **Intel/COAWST toolchain** — `coawst.bash_env_intel.source_oneapi` (`COAWST_ENV`)
- **Python** — Miniforge + the `hindcast` conda env (`hindcast.yml`)
- **LiveOcean** — `LO/` code (editable `lo_tools`)
- **Path SST** — `env`, sourced by the workflow repo

Related repos (all cloned under `$HOME`):

| Directory | Repo | Content |
|---|---|---|
| `~/inacawo-deps` (+ `~/apps`) | [devmetmar/inacawo-deps](https://github.com/devmetmar/inacawo-deps) | libraries, `hindcast` conda env, LiveOcean, `COAWST_ENV` (this repo) |
| `~/inacawo-src` | [devmetmar/inacawo-src](https://github.com/devmetmar/inacawo-src) | build scripts and headers only; you compile `binaries/{ramp_tides,no_ramp_tides}/coawstM` (source tarball is not in git) |
| `~/inacawo-iht` | [devmetmar/inacawo-iht](https://github.com/devmetmar/inacawo-iht) | hindcast working directory (preprocess / run / postprocess) |

## Quick start (participants)

Same order in all three READMEs. This repo is step 2.

```bash
# 1) Clone all three under $HOME
cd $HOME
git clone https://github.com/devmetmar/inacawo-deps.git
git clone https://github.com/devmetmar/inacawo-src.git
git clone https://github.com/devmetmar/inacawo-iht.git

# 2) Libraries in ~/apps (~37 GiB), Miniforge, and the hindcast conda env.
#    --offline still installs the COAWST libraries; only the conda env is shared.
cd $HOME/inacawo-deps
bash install_hindcast_env.bash             # online: private env
# or, on a flaky network (shared read-only env, no downloads):
bash install_hindcast_env.bash --offline
# private env only: --force-recreate
# other installer flags are listed below

# 3) Compile both coawstM (Intel via COAWST_ENV, not conda).
#    IHT accounts: --partition DEV1. Omit it only if your account is allowed
#    on HDCAST; otherwise the wrapper selects DEV1 itself.
cd $HOME/inacawo-src
bash build_coawst.bash --sbatch --partition DEV1

# 4) Daily workflow (paths + conda activate hindcast)
source $HOME/inacawo-iht/setup_env.bash
```

Prerequisites: Linux x86_64 with `/scratch`, Intel oneAPI at
`/opt/software/intel/oneapi` (used by `COAWST_ENV`), `curl` for the first
Miniforge download (unless cached), and **~37 GiB free under `$HOME`** for the
COAWST model deps.

## Layout

```
$HOME/inacawo-deps/                    # this repo (DEPS_BASE)
  env                                  # path SST (LO, conda, APPS_BASE, LIBDEP, …)
  coawst.bash_env_intel.source_oneapi  # Intel/COAWST toolchain (COAWST_ENV)
  install_hindcast_env.bash            # wrapper: dirs + COAWST deps + Miniforge + hindcast env
  hindcast.yml                         # hindcast conda env spec
  LO/                                  # LiveOcean code (pip editable lo_tools)
  miniforge3/                          # local Miniforge (gitignored; created by wrapper)
  hindcast_env.prefix                  # active hindcast env prefix (gitignored; written by wrapper)

$HOME/apps/                            # APPS_BASE (outside the repo; created by wrapper)
  cawo_depends/intel_2021.5.1/
    build/{bin,include,lib}            # NetCDF-C/F, HDF5, MCT, jasper, … → LIBDEP=build/lib
    src/                               # sources + build scripts of the deps
    .inacawo_installed                 # marker: tarball, sha256, install date

$HOME/inacawo-iht/preprocess/
  LO_user/                             # LO user config + forcing drivers
  get_era5/ get_glorys/ get_roms_icbc/ get_swan_bry/ wps_run/

/scratch/$USER/inacawo-iht/            # CAWO_HINDCAST_BASE
  cawo_input/                          # CAWO_INPUT
    LO_data/ LO_output/ LO_roms/
    roms_forcing/ era5/ mercator/ wps_run/ swan_bcs/ …
  cawo_hindcast_run/ cawo_output/ cawo_post/
```

## What the installer does

`bash install_hindcast_env.bash`:

1. Creates the per-user dirs under `/scratch/$USER/inacawo-iht/cawo_input/`
   (`LO_data`, `LO_data/grids`, `LO_output`, `LO_roms`, `roms_forcing`), plus
   `LO_user` if `inacawo-iht` is already cloned.
2. Extracts the **COAWST model deps** into `$HOME/apps/cawo_depends/intel_2021.5.1`
   (skipped if already present; see below).
3. Installs **Miniforge3** into `$HOME/inacawo-deps/miniforge3` if missing.
4. Creates (or updates) the **`hindcast`** env from `hindcast.yml` (includes
   editable `./LO/lo_tools`), or points at the shared env with `--offline`.
5. Prints elapsed time for **COAWST deps**, **Miniforge**, **hindcast env**,
   and **total**, plus the resolved paths.

The `hindcast` env is always created at **`$CONDA_BASE/envs/hindcast`**
(not `~/envs`), even if `~/.condarc` sets a different `envs_dirs`.

### Options

```bash
# COAWST model deps
bash install_hindcast_env.bash --only-coawst-deps     # model libs only (no conda)
bash install_hindcast_env.bash --skip-coawst-deps     # conda / LO only
bash install_hindcast_env.bash --force-coawst-deps    # remove + re-extract model libs
bash install_hindcast_env.bash --coawst-tarball PATH  # override deps tarball

# hindcast conda env
bash install_hindcast_env.bash --force-recreate       # delete + recreate private env
bash install_hindcast_env.bash --offline              # no downloads; use shared scratch env
bash install_hindcast_env.bash --offline --from-clone PATH  # private copy of an env (slow)
bash install_hindcast_env.bash --cache-dir DIR        # override cache root
bash install_hindcast_env.bash --prefetch-miniforge   # download installer into cache, exit
bash install_hindcast_env.bash --seed-pkgs-from DIR   # maintainer: seed conda pkgs cache
bash install_hindcast_env.bash --help
```

## COAWST model deps (NetCDF, HDF5, MCT, …)

Prebuilt with Intel oneAPI 2021.5.1: NetCDF-C 4.6.1, NetCDF-Fortran 4.4.5,
HDF5 1.10.6, MCT 2.6.0, jasper, libpng, curl, szip, zlib, udunits, expat.
The wrapper extracts the shared tarball into `$APPS_BASE` (default `$HOME/apps`):

```
/scratch/cawohdcst_ft2/inacawo-iht/deps_tarballs/   # CAWO_DEPS_TARBALL_DIR (a+rX)
  apps.cawo_depends.mdclogin0.tar.gz              # 563 MB compressed
  SHA256SUMS
```

- Skipped if `$LIBDEP/libnetcdff.so` already exists (use `--force-coawst-deps` to redo).
- Verifies sha256 when `SHA256SUMS` sits next to the tarball.
- Rewrites the original build root baked into `nc-config`, `nf-config`, `*.la`,
  `*.pc`, `*.settings` to the new location, then checks `nf-config --prefix`
  / `nc-config --libdir` and the key libraries.
- Needs **~36 GiB** free in `$APPS_BASE` (almost all of it is netcdf-c test
  output under `src/`; `build/` itself is ~48 MB) and takes ~4–5 min.

Use them via `COAWST_ENV` (sets Intel compilers, `NETCDF`, `NC_CONFIG`,
`NF_CONFIG`, `HDF5`, `MCT_*`, `JASPER*`, `LD_LIBRARY_PATH`, …). Source it only
in shells/jobs that build or run COAWST/WPS — it runs `module purge`:

```bash
source $HOME/inacawo-deps/env
source "${COAWST_ENV}"
nf-config --flibs
```

## hindcast conda env: online vs offline

| Mode | Env location | Package cache |
|---|---|---|
| online (default) | private `$HOME/inacawo-deps/miniforge3/envs/hindcast` | private `/scratch/$USER/inacawo-deps-cache` |
| `--offline` | shared read-only `/scratch/cawohdcst_ft2/inacawo-deps-cache/envs/hindcast` | none (no downloads, no copy) |
| `--offline --from-clone PATH` | private copy of `PATH` (rsync + prefix rewrite) | — |

Shared cache (maintained by `cawohdcst_ft2`, `chmod -R a+rX`):

```
/scratch/cawohdcst_ft2/inacawo-deps-cache/
  miniforge/Miniforge3-Linux-x86_64.sh   # reused by online installs if present
  conda-pkgs/
  envs/hindcast/                         # SHARED read-only hindcast env (--offline)
```

With `--offline`, the wrapper writes the shared prefix into `hindcast_env.prefix`;
`env` / `setup_env.bash` then activate it. Each user's own
`$HOME/inacawo-deps/LO/lo_tools` is still used via `$LO` (the shared env is
read-only, so nothing is pip-installed into it).

Other users **cannot** read `/home/cawohdcst_ft2/...` (mode 700). Anything
meant to be shared (installers, tarballs, reference envs) must live on
`/scratch/cawohdcst_ft2/...` with `chmod -R a+rX`.

## Environment variables

Defined in `env` only — `inacawo-iht/env` sources this file and must not
redefine them:

| Variable | Default |
|---|---|
| `DEPS_BASE` | `$HOME/inacawo-deps` |
| `CONDA_BASE`, `CONDA_ENVS_DIRS` | `$DEPS_BASE/miniforge3`, `$CONDA_BASE/envs` (fallback `$HOME/opt/miniforge3`) |
| `HINDCAST_ENV_PREFIX` | from `hindcast_env.prefix` → local env → shared env |
| `HINDCAST_SHARED_ENV` | `/scratch/cawohdcst_ft2/inacawo-deps-cache/envs/hindcast` |
| `CAWO_HINDCAST_BASE`, `CAWO_INPUT` | `/scratch/$USER/inacawo-iht`, `$CAWO_HINDCAST_BASE/cawo_input` |
| `LO`, `LO_USER` | `$DEPS_BASE/LO`, `$HOME/inacawo-iht/preprocess/LO_user` |
| `LO_DATA`, `LO_OUTPUT`, `LO_ROMS` | `$CAWO_INPUT/LO_data`, `…/LO_output`, `…/LO_roms` |
| `LO_ROMS_SOURCE_ALT`, `LO_ROMS_VARINFO` | `/scratch/cawohdcst_ft/home/cawohdcst/LO_roms_source_alt`, `…/varinfo/varinfo.yaml` |
| `APPS_BASE` | `$HOME/apps` |
| `CAWO_DEPS_TARBALL_DIR`, `CAWO_DEPS_TARBALL` | `/scratch/cawohdcst_ft2/inacawo-iht/deps_tarballs`, `…/apps.cawo_depends.mdclogin0.tar.gz` |
| `LIBDEP` | `$APPS_BASE/cawo_depends/intel_2021.5.1/build/lib` |
| `COAWST_ENV` | `$DEPS_BASE/coawst.bash_env_intel.source_oneapi` |

Variables using `${VAR:-default}` (e.g. `APPS_BASE`, `CONDA_BASE`,
`LO_ROMS_SOURCE_ALT`) can be overridden by exporting them before sourcing `env`
or running the wrapper.

## Maintainer tasks (run as `cawohdcst_ft2`)

Refresh the shared COAWST deps tarball:

```bash
D=/scratch/cawohdcst_ft2/inacawo-iht/deps_tarballs
cp -p $HOME/apps/tars/apps.cawo_depends.mdclogin0.tar.gz $D/
(cd $D && sha256sum apps.cawo_depends.mdclogin0.tar.gz > SHA256SUMS)
chmod 755 $D && chmod 644 $D/*
```

Refresh the shared hindcast env after updating `hindcast.yml`
(`SRC` = an up-to-date private hindcast env):

```bash
SRC=$HOME/opt/miniforge3/envs/hindcast
rm -rf /scratch/cawohdcst_ft2/inacawo-deps-cache/envs/hindcast
conda create -p /scratch/cawohdcst_ft2/inacawo-deps-cache/envs/hindcast --clone "$SRC" -y
chmod -R a+rX /scratch/cawohdcst_ft2/inacawo-deps-cache
```

Prefetch the Miniforge installer into the shared cache:

```bash
bash install_hindcast_env.bash --prefetch-miniforge
```

## Manual conda install (alternative)

If you already manage conda yourself:

```bash
cd $HOME/inacawo-deps
mamba env create -f hindcast.yml
# or: conda env create -f hindcast.yml
conda activate hindcast
```

Must run from this directory so `./LO/lo_tools` resolves. Override
`CONDA_BASE` before sourcing `env` if your prefix is not under
`inacawo-deps/miniforge3` or `$HOME/opt/miniforge3`.
