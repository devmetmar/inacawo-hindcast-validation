#!/bin/bash

set -euo pipefail

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "${SCRIPT_PATH}")"
STARTED_AT="$(date +%s)"

usage() {
  echo "Usage: $0 --start YYYYMMDD --end YYYYMMDD"
}

validate_date() {
  local value="$1"
  [[ "${value}" =~ ^[0-9]{8}$ ]] || return 1
  [[ "$(date -d "${value}" +%Y%m%d 2>/dev/null)" == "${value}" ]]
}

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
: "${CAWO_HINDCAST_BASE:?setup_env.bash did not define CAWO_HINDCAST_BASE}"

ERA5_ROOT="${WRF_ERA5_ERA5_ROOT:-/scratch/cawohdcst/data/era5}"
WEIGHTS_FILE="${WRF_ERA5_WEIGHTS_FILE:-/scratch/cawohdcst/data/postprocessed/weights_era5_to_wrf_bilinear.nc}"
WRF_DIR="${CAWO_POST}/wrf2d"
if [[ ! -d "${WRF_DIR}" ]]; then
  echo "Postprocessed WRF directory not found: ${WRF_DIR}" >&2
  exit 1
fi
if [[ ! -d "${ERA5_ROOT}" ]]; then
  echo "ERA5 directory not found: ${ERA5_ROOT}" >&2
  exit 1
fi

RUN_ID="$(date +%Y%m%dT%H%M%S)_$$"
RUN_DIR="${CAWO_HINDCAST_BASE}/validation/wrf_era5_comparison/${START_DATE}_${END_DATE}/run_${RUN_ID}"
OUT_DIR="${RUN_DIR}/output"
LOG_DIR="${RUN_DIR}/logs"
mkdir -p "${OUT_DIR}" "${LOG_DIR}"
LAUNCH_LOG="${LOG_DIR}/launcher.log"
exec > >(tee -a "${LAUNCH_LOG}") 2>&1

finish() {
  local status=$?
  trap - EXIT
  local finished_at
  finished_at="$(date +%s)"
  printf 'Launcher finished: %s\n' "$(date --date="@${finished_at}" '+%Y-%m-%d %H:%M:%S %z')"
  printf 'Launcher exit status: %s\n' "${status}"
  printf 'Total elapsed time (including SLURM wait): %s seconds\n' "$((finished_at - STARTED_AT))"
  exit "${status}"
}
trap finish EXIT

mkdir -p "${LOG_DIR}"
echo "WRF/ERA5 comparison: ${START_DATE}-${END_DATE}"
echo "WRF input: ${WRF_DIR}"
echo "ERA5 input: ${ERA5_ROOT}"
echo "Regridding weights: ${WEIGHTS_FILE}"
echo "Run directory: ${RUN_DIR}"
echo "Output directory: ${OUT_DIR}"
echo "Launcher log: ${LAUNCH_LOG}"

partition="${IHT_SLURM_PARTITION:-DEV1}"
echo "SLURM partition: ${partition}"
echo "Submitting four extraction tasks and waiting for completion..."
ARRAY_STARTED_AT="$(date +%s)"
if job_id="$(
  sbatch --parsable --wait \
    --chdir="${SCRIPT_DIR}" \
    --array="0-3%4" \
    --job-name=wrf_era5_ts \
    --output="${LOG_DIR}/wrf_era5_ts_%A_%a.out" \
    --error="${LOG_DIR}/wrf_era5_ts_%A_%a.err" \
    --partition="${partition}" \
    --export="ALL,WRF_ERA5_START_DATE=${START_DATE},WRF_ERA5_END_DATE=${END_DATE},WRF_ERA5_RUN_DIR=${RUN_DIR},WRF_ERA5_SCRIPT_DIR=${SCRIPT_DIR}" \
    "${SCRIPT_DIR}/slurm_save_wrf_era5_series_array_clean.bash"
)"; then
  ARRAY_FINISHED_AT="$(date +%s)"
  echo "SLURM array completed: ${job_id}"
  echo "Stage elapsed time (SLURM array, including queue time): $((ARRAY_FINISHED_AT - ARRAY_STARTED_AT)) seconds"
  echo "Per-variable task durations are recorded in ${LOG_DIR}/wrf_era5_ts_<job-id>_<task-id>.out"
else
  sbatch_status=$?
  ARRAY_FINISHED_AT="$(date +%s)"
  echo "ERROR: SLURM array failed with exit status ${sbatch_status}."
  echo "Stage elapsed time before failure: $((ARRAY_FINISHED_AT - ARRAY_STARTED_AT)) seconds"
  if [[ -n "${job_id}" ]]; then
    job_id="${job_id%%;*}"
    echo "SLURM job ID: ${job_id}"
  fi
  echo "Inspecting task logs in ${LOG_DIR}:"
  shopt -s nullglob
  task_logs=("${LOG_DIR}"/wrf_era5_ts_*.out "${LOG_DIR}"/wrf_era5_ts_*.err)
  if ((${#task_logs[@]} == 0)); then
    echo "No task logs were created; check SLURM submission/account/partition diagnostics."
  else
    for task_log in "${task_logs[@]}"; do
      echo "--- ${task_log} (last 40 lines) ---"
      tail -n 40 "${task_log}"
    done
  fi
  exit "${sbatch_status}"
fi

echo "Starting drift analysis..."
ANALYSIS_STARTED_AT="$(date +%s)"
DRIFT_DIR="${OUT_DIR}/drift_analysis"
python -u "${SCRIPT_DIR}/wrf_era5_drift_analysis.py" \
  --pressure "${OUT_DIR}/pressure_${START_DATE}_${END_DATE}.nc" \
  --rh2 "${OUT_DIR}/rh2_${START_DATE}_${END_DATE}.nc" \
  --u10 "${OUT_DIR}/u10_${START_DATE}_${END_DATE}.nc" \
  --v10 "${OUT_DIR}/v10_${START_DATE}_${END_DATE}.nc" \
  --outdir "${DRIFT_DIR}"
ANALYSIS_FINISHED_AT="$(date +%s)"
echo "Stage elapsed time (drift analysis): $((ANALYSIS_FINISHED_AT - ANALYSIS_STARTED_AT)) seconds"
echo "Drift-analysis outputs: ${DRIFT_DIR}"
