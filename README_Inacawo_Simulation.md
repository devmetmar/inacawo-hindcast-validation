# InaCAWO Hindcast (`inacawo-iht`)

Reproducible WRF–ROMS–SWAN hindcast workflow for the CAWO domain (COAWST).
Each calendar day runs as a separate integration (`fYYYYMMDD`).

## Companion repos

| Repo | Role |
|------|------|
| `$HOME/inacawo-deps` | Conda env (`hindcast`) + COAWST libraries in `~/apps` + LiveOcean (`LO/`) |
| `$HOME/inacawo-iht` | **This repo** — preprocess / run / postprocess scripts |
| `$HOME/inacawo-src` | Build scripts and headers only. You compile `binaries/{ramp_tides,no_ramp_tides}/coawstM` yourself; the model source is not in git |

## One-time setup (new machine)

Do these in order. Daily work starts only after step 4.

```bash
# 1) Clone all three under $HOME
git clone https://github.com/devmetmar/inacawo-deps.git $HOME/inacawo-deps
git clone https://github.com/devmetmar/inacawo-src.git  $HOME/inacawo-src
git clone https://github.com/devmetmar/inacawo-iht.git  $HOME/inacawo-iht

# 2) Libraries in ~/apps (~37 GiB), Miniforge, and the hindcast conda env.
#    --offline still installs the COAWST libraries; only the conda env is shared.
# bash $HOME/inacawo-deps/install_hindcast_env.bash             # online: private env
# or, on a flaky network (shared read-only env, no downloads):
bash $HOME/inacawo-deps/install_hindcast_env.bash --offline
# private env only: --force-recreate
# other installer flags: inacawo-deps/README.md
# compile flags (--variant, --time, --force-extract): inacawo-src/README.md

# 3) Compile both coawstM. This uses the Intel toolchain (COAWST_ENV),
#    not the conda env. Two jobs, 1 node x 96 cores each.
#    IHT accounts: --partition DEV1. Omit it only if your account is allowed
#    on HDCAST; otherwise the wrapper selects DEV1 itself.
cd $HOME/inacawo-src
bash build_coawst.bash --sbatch --partition DEV1
# squeue -u $USER
# binaries/ramp_tides/coawstM and binaries/no_ramp_tides/coawstM

# 4) Activate the hindcast workflow (paths + conda activate hindcast)
source $HOME/inacawo-iht/setup_env.bash
```

API credentials are optional on that same command (one account per user):

```bash
source $HOME/inacawo-iht/setup_env.bash \
  --cds-key 'UID:KEY' --cmems-user U --cmems-pass P
# or edit dummies / copernicusmarine login — see src/credentials/README.md
# Operators only: IHT_VAULT_CREDS=1 + src/credentials/vault-token
```

## Environment bootstrap

Every SLURM/interactive script should load:

```bash
source $HOME/inacawo-iht/setup_env.bash
# optional:
# source setup_env.bash --cds-key 'UID:KEY' --cmems-user U --cmems-pass P
```

That sources `env` → `inacawo-deps/env`, then helpers under `src/` (`setup_vault.bash`,
`setup_credentials.bash`), soft-checks credentials, and `conda activate hindcast`.
Use this for preprocess, hindcast, and postprocess. Compiling `coawstM` does not:
`build_coawst.bash` sources `inacawo-deps/env` and `COAWST_ENV` itself.

**Credentials:** CLI args above, or personal files — see [src/credentials/README.md](src/credentials/README.md).  
**Vault (opt-in):** `IHT_VAULT_CREDS=1` — see `src/setup_vault.bash`.

Key variables (see `inacawo-deps/env` + `env`):

| Variable | Meaning |
|----------|---------|
| `WORK_BASE` | `$HOME/inacawo-iht` |
| `SCRATCH` | `/scratch/$USER` |
| `MODEL_BASE` | `$HOME/inacawo-src` |
| `COAWST_ENV` | `$DEPS_BASE/coawst.bash_env_intel.source_oneapi` (Intel toolchain; sourced by `build_coawst.bash`, WPS, and the model run — not by `conda activate`) |
| `CAWO_HINDCAST_BASE` | `$SCRATCH/inacawo-iht` |
| `LO` / `LO_USER` | deps code / `preprocess/LO_user` |
| `LO_DATA` / `LO_OUTPUT` | `$SCRATCH/inacawo-iht/cawo_input/LO_{data,output}` |
| `CAWO_INPUT` | `$SCRATCH/inacawo-iht/cawo_input` |
| `ROMS_FORCING` | `$CAWO_INPUT/roms_forcing` (per-user writable) |
| `ERA5_BASE_DIR`, `GLORYS_BASE_DIR`, `WPS_RUN_DIR` | under `$CAWO_INPUT` |

Shared site inputs default to `/scratch/cawohdcst_ft/data` (`SHARED_DATA` — also mirrored under `cawohdcst`). Override if needed:

```bash
export SHARED_DATA=/scratch/cawohdcst_ft/data   # default
# or individually:
export WPS_STATIC_DIR=/path/to/wps_static
export WRF_STATIC_DIR=/path/to/wrf_static
export GRID_DATA=/path/to/grids
export SWAN_STATIC=/path/to/swan_static_cycle
```

| Shared var | Default under `$SHARED_DATA` |
|------------|------------------------------|
| `WPS_STATIC_DIR` | `static/wps/wps-4.3.1_static` |
| `WRF_*` | `static/wrf/...` |
| `GEOGRID_FILE` | `wps_run/geogrid_v43/geo_em.d01.nc.ID03F3` |
| `GRID_DATA` | `grids` |
| `SWAN_STATIC` / `VARINFO` / `GRID_SCRIP` | `cawo_hindcast_run/...` |

## Directory layout

```
inacawo-iht/
  setup_env.bash          # source this first
  env                     # iht workflow paths (sources inacawo-deps/env)
  preprocess/             # see preprocess/README.md
    get_era5/ 
    get_glorys/ 
    wps_run/ 
    get_swan_bry/ 
    get_roms_icbc/ 
    LO_user/
  hindcast_run/           # see hindcast_run/README.md
  postprocess/            # see postprocess/README.md
  README.md
```

Each major subdirectory has its own `README.md` with scripts, env vars, and usage.

## Workflow

Always:

```bash
source $HOME/inacawo-iht/setup_env.bash
cd $WORK_BASE
```

Use `hindcast` for all stages (download, LO forcing, postprocess).

**Slurm partition:** IHT accounts use `--partition DEV1` (or
`IHT_SLURM_PARTITION=DEV1`). Preprocess, hindcast, postprocess, and
`build_coawst.bash` select `HDCAST` only when the Slurm account is in that
partition’s `AllowAccounts`; otherwise they select `DEV1` (so jobs do not sit
in `PENDING (PartitionConfig)`). Omit `--partition` only if your account is
allowed on `HDCAST`.

### 1. Preprocess

Preferred entrypoint (dates via CLI; see `preprocess/README.md`):

```bash
cd preprocess

# Download dataset
./run_preprocess.bash --start YYYYMMDD --end YYYYMMDD --stage download
# TC Seroja (shared archive, no CDS/CMEMS): ≤7 days
./run_preprocess.bash --start 20210404 --end 20210410 --stage download --offline

# Preprocessing
./run_preprocess.bash --start YYYYMMDD --end YYYYMMDD --stage wps
./run_preprocess.bash --start YYYYMMDD --end YYYYMMDD --stage swan
./run_preprocess.bash --start YYYYMMDD --end YYYYMMDD --stage roms --day1
```

LiveOcean paths come from `preprocess/LO_user/get_lo_info.py` (and `get_roms_icbc/utils/get_lo_info.py` for the local utils import).

### 2. Run setup + model

Preferred entrypoint (dates via CLI; see `hindcast_run/README.md`):

```bash
./run_hindcast.bash --start YYYYMMDD --end YYYYMMDD --day1
# or for consecutive day without ramp tide
./run_hindcast.bash --start YYYYMMDD --end YYYYMMDD
```

`--day1` applies day1 templates + ramp binary to the **first** day of the
range; later days use no-ramp + default templates. Quiet logs under
`$WORK_BASE/logs/hindcast/`.

### 3. Postprocess

Preferred entrypoint (dates via CLI; see `postprocess/README.md`):

```bash
./run_postprocess.bash --start YYYYMMDD --end YYYYMMDD --stage roms2d
./run_postprocess.bash --start YYYYMMDD --end YYYYMMDD --stage roms3d
./run_postprocess.bash --start YYYYMMDD --end YYYYMMDD --stage wrf2d
./run_postprocess.bash --start YYYYMMDD --end YYYYMMDD --stage wrf3d
```

Quiet logs under `$WORK_BASE/logs/postprocess/`. Shared archive tutorial:
`postprocess/tutorials/tutorial_postprocessed_hindcast.ipynb`.

## LiveOcean (preprocess only)

| Piece | Location |
|-------|----------|
| Code (`lo_tools`) | `$HOME/inacawo-deps/LO` via `hindcast.yml` |
| User config / drivers | `preprocess/LO_user/` |
| Wrappers | `preprocess/get_roms_icbc/` |
| Data / output | `/scratch/$USER/inacawo-iht/cawo_input/LO_{data,output}` |

## Notes

- Prefer `get_roms_icbc/` SLURM scripts as the supported entrypoints; `LO_user/forcing/` holds the forcing implementations they call or mirror.
- Do not hardcode usernames; paths go through `env` / `setup_env.bash`.
- Static WRF/WPS/SWAN assets are **not** in this repo — set via `env` overrides.
