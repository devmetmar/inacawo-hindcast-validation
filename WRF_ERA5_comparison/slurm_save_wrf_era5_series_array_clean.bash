#!/bin/bash
#SBATCH --job-name=wrf_era5_ts
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=50G
#SBATCH --time=30:00:00

# Internal worker for run_wrf_comparison.bash; do not submit directly.
set -euo pipefail

SCRIPT_DIR="${WRF_ERA5_SCRIPT_DIR:?Missing source directory submitted by run_wrf_comparison.bash}"
PYTHON_BIN="python"
ERA5_ROOT="${WRF_ERA5_ERA5_ROOT:-/scratch/cawohdcst/data/era5}"
WEIGHTS_FILE="${WRF_ERA5_WEIGHTS_FILE:-/scratch/cawohdcst/data/postprocessed/weights_era5_to_wrf_bilinear.nc}"
CHUNK_SIZE=24

validate_date() {
  local value="$1"
  [[ "${value}" =~ ^[0-9]{8}$ ]] || return 1
  [[ "$(date -d "${value}" +%Y%m%d 2>/dev/null)" == "${value}" ]]
}

TASK_STARTED_SECONDS=$SECONDS
finish_task() {
  local status=$?
  trap - EXIT
  local elapsed=$((SECONDS - TASK_STARTED_SECONDS))
  printf 'Task %s finished with exit status %s; elapsed time: %s seconds\n' \
    "${SLURM_ARRAY_TASK_ID:-unknown}" "${status}" "${elapsed}"
  exit "${status}"
}
trap finish_task EXIT

START_DATE="${WRF_ERA5_START_DATE:?Missing submitted --start date}"
END_DATE="${WRF_ERA5_END_DATE:?Missing submitted --end date}"
RUN_DIR="${WRF_ERA5_RUN_DIR:?Missing submitted run directory}"
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
OUT_DIR="${RUN_DIR}/output"
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

if [[ ! -f "${SCRIPT_DIR}/${SCRIPT}" ]]; then
  echo "Python driver script not found: ${SCRIPT_DIR}/${SCRIPT}" >&2
  exit 1
fi

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
