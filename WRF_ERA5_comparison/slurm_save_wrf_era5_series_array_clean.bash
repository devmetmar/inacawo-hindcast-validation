#!/bin/bash
#SBATCH --job-name=wrf_era5_ts
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=50G
#SBATCH --time=30:00:00
#SBATCH --output=logs/wrf_era5_ts_%A_%a.out
#SBATCH --error=logs/wrf_era5_ts_%A_%a.err

set -euo pipefail

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "${SCRIPT_PATH}")"
PYTHON_BIN="python"
ERA5_ROOT="/scratch/cawohdcst/data/era5"
WEIGHTS_FILE="/scratch/cawohdcst/data/postprocessed/weights_era5_to_wrf_bilinear.nc"
CHUNK_SIZE=24

usage() {
  echo "Usage: $0 --start YYYYMMDD --end YYYYMMDD"
}

validate_date() {
  local value="$1"
  [[ "${value}" =~ ^[0-9]{8}$ ]] || return 1
  [[ "$(date -d "${value}" +%Y%m%d 2>/dev/null)" == "${value}" ]]
}

if [[ -z "${SLURM_JOB_ID:-}" ]]; then
  START_DATE=""
  END_DATE=""

  while (($#)); do
    case "$1" in
      --start)
        (($# >= 2)) || { usage >&2; exit 2; }
        START_DATE="$2"
        shift 2
        ;;
      --end)
        (($# >= 2)) || { usage >&2; exit 2; }
        END_DATE="$2"
        shift 2
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        echo "Unknown argument: $1" >&2
        usage >&2
        exit 2
        ;;
    esac
  done

  if ! validate_date "${START_DATE}" || ! validate_date "${END_DATE}"; then
    echo "Both --start and --end must be valid dates in YYYYMMDD format." >&2
    exit 2
  fi
  if [[ "${END_DATE}" < "${START_DATE}" ]]; then
    echo "--end must not be earlier than --start." >&2
    exit 2
  fi

  IHT_ROOT="${WORK_BASE:-${HOME}/inacawo-iht}"
  SETUP_ENV="${IHT_ROOT}/setup_env.bash"
  if [[ ! -f "${SETUP_ENV}" ]]; then
    echo "InaCAWO setup script not found: ${SETUP_ENV}" >&2
    exit 1
  fi
  # shellcheck source=/dev/null
  source "${SETUP_ENV}"
  : "${CAWO_POST:?setup_env.bash did not define CAWO_POST}"
  if [[ ! -d "${CAWO_POST}/wrf2d" ]]; then
    echo "Postprocessed WRF directory not found: ${CAWO_POST}/wrf2d" >&2
    exit 1
  fi
  if [[ ! -d "${ERA5_ROOT}" ]]; then
    echo "ERA5 directory not found: ${ERA5_ROOT}" >&2
    exit 1
  fi

  mkdir -p "${SCRIPT_DIR}/logs"
  sbatch_args=(
    --chdir="${SCRIPT_DIR}"
    --array="0-3%4"
    --output="${SCRIPT_DIR}/logs/wrf_era5_ts_%A_%a.out"
    --error="${SCRIPT_DIR}/logs/wrf_era5_ts_%A_%a.err"
    --export="ALL,WRF_ERA5_START_DATE=${START_DATE},WRF_ERA5_END_DATE=${END_DATE}"
  )
  sbatch_args+=(--partition="${IHT_SLURM_PARTITION:-DEV1}")
  echo "Submitting WRF/ERA5 comparison for ${START_DATE}-${END_DATE}"
  echo "WRF input: ${CAWO_POST}/wrf2d"
  echo "ERA5 input: ${ERA5_ROOT}"
  echo "Output: ${SCRIPT_DIR}/output"
  sbatch --parsable "${sbatch_args[@]}" "${SCRIPT_PATH}"
  exit
fi

START_DATE="${WRF_ERA5_START_DATE:?Missing submitted --start date}"
END_DATE="${WRF_ERA5_END_DATE:?Missing submitted --end date}"
if ! validate_date "${START_DATE}" || ! validate_date "${END_DATE}"; then
  echo "Invalid submitted date range: ${START_DATE}-${END_DATE}" >&2
  exit 2
fi
if [[ "${END_DATE}" < "${START_DATE}" ]]; then
  echo "Submitted --end date is earlier than --start date." >&2
  exit 2
fi

IHT_ROOT="${WORK_BASE:-${HOME}/inacawo-iht}"
SETUP_ENV="${IHT_ROOT}/setup_env.bash"
if [[ ! -f "${SETUP_ENV}" ]]; then
  echo "InaCAWO setup script not found: ${SETUP_ENV}" >&2
  exit 1
fi
# shellcheck source=/dev/null
source "${SETUP_ENV}"
: "${CAWO_POST:?setup_env.bash did not define CAWO_POST}"

WRF_DIR="${CAWO_POST}/wrf2d"
OUT_DIR="${SCRIPT_DIR}/output"
mkdir -p "${OUT_DIR}"
if [[ ! -d "${WRF_DIR}" ]]; then
  echo "Postprocessed WRF directory not found: ${WRF_DIR}" >&2
  exit 1
fi
if [[ ! -d "${ERA5_ROOT}" ]]; then
  echo "ERA5 directory not found: ${ERA5_ROOT}" >&2
  exit 1
fi

case "${SLURM_ARRAY_TASK_ID:?This script must run as an array job}" in
  0)
    VARIABLE="pressure"
    SCRIPT="save_pressure_series_clean.py"
    ;;
  1)
    VARIABLE="u10"
    SCRIPT="save_u10_series_clean.py"
    ;;
  2)
    VARIABLE="v10"
    SCRIPT="save_v10_series_clean.py"
    ;;
  3)
    VARIABLE="rh2"
    SCRIPT="save_rh2_series_clean.py"
    ;;
  *)
    echo "Unexpected array task: ${SLURM_ARRAY_TASK_ID}" >&2
    exit 2
    ;;
esac

OUTPUT="${OUT_DIR}/${VARIABLE}_${START_DATE}_${END_DATE}.nc"

echo "Variable: ${VARIABLE}"
echo "Dates: ${START_DATE}-${END_DATE}"
echo "WRF input: ${WRF_DIR}"
echo "ERA5 input: ${ERA5_ROOT}"
echo "Output: ${OUTPUT}"

"${PYTHON_BIN}" -u "${SCRIPT_DIR}/${SCRIPT}" \
  "${WRF_DIR}" \
  "${ERA5_ROOT}" \
  --start "${START_DATE}" \
  --end "${END_DATE}" \
  "${OUTPUT}" \
  --chunk-size "${CHUNK_SIZE}" \
  --weights-file "${WEIGHTS_FILE}"
