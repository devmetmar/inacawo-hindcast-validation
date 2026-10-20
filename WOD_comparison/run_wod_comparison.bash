#!/usr/bin/env bash
set -eo pipefail

LOG_FILE=""
TOTAL_START=$SECONDS
STAGE_ORDER=()
declare -A STAGE_DURATIONS=()
declare -A STAGE_RESULTS=()
ACTIVE_STAGE=""
ACTIVE_STAGE_START=0

log() {
    local message
    message="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    if [[ -n "$LOG_FILE" ]]; then
        printf '%s\n' "$message" | tee -a "$LOG_FILE" >&2
    else
        printf '%s\n' "$message" >&2
    fi
}

format_duration() {
    local seconds=$1
    printf '%02d:%02d:%02d' "$((seconds / 3600))" "$(((seconds % 3600) / 60))" "$((seconds % 60))"
}

stage_start() {
    ACTIVE_STAGE="$1"
    ACTIVE_STAGE_START=$SECONDS
    STAGE_ORDER+=("$1")
    log "STAGE START: $ACTIVE_STAGE"
}

stage_finish() {
    local result=$1
    local elapsed=$((SECONDS - ACTIVE_STAGE_START))
    STAGE_DURATIONS["$ACTIVE_STAGE"]=$elapsed
    STAGE_RESULTS["$ACTIVE_STAGE"]=$result
    log "STAGE END: $ACTIVE_STAGE | $result | duration=$(format_duration "$elapsed")"
    ACTIVE_STAGE=""
}

finish_launcher() {
    local status=$1
    local total_elapsed=$((SECONDS - TOTAL_START))
    trap - EXIT

    if [[ -n "$ACTIVE_STAGE" ]]; then
        if (( status == 0 )); then
            stage_finish "INCOMPLETE"
        else
            stage_finish "FAILED (exit $status)"
        fi
    fi
    if (( status != 0 )); then
        log "ERROR: launcher exited with status $status."
    fi
    log "===== WOD LAUNCHER DURATION SUMMARY ====="
    for stage in "${STAGE_ORDER[@]}"; do
        log "SUMMARY: $stage | ${STAGE_RESULTS["$stage"]} | duration=$(format_duration "${STAGE_DURATIONS["$stage"]}")"
    done
    log "SUMMARY: total launcher duration=$(format_duration "$total_elapsed")"
    if (( status == 0 )); then
        log "SUMMARY: final status=SUCCESS"
    else
        log "SUMMARY: final status=FAILED (exit $status)"
    fi
}

trap 'finish_launcher "$?"' EXIT

submit_job() {
    if SBATCH_RESULT=$(sbatch \
        --partition="$PARTITION" \
        --job-name="wod_${START_DATE}_${END_DATE}" \
        --output="$SLURM_LOG" \
        --error="$SLURM_ERROR_LOG" \
        --export="ALL,IHT_WOD_START=${START_DATE},IHT_WOD_END=${END_DATE},IHT_SETUP_ENV=${SETUP_ENV},IHT_WOD_SCRIPT_DIR=${SCRIPT_DIR},IHT_WOD_FILE=${WOD_FILE}" \
        "$SCRIPT_DIR/slurm_extract_roms2wod.bash"); then
        log "$SBATCH_RESULT"
        if [[ "$SBATCH_RESULT" =~ Submitted[[:space:]]batch[[:space:]]job[[:space:]]([0-9]+) ]]; then
            log "Fresh output directory: ${RUN_DIR}/jobs/${BASH_REMATCH[1]}_0"
        fi
    else
        local status=$?
        log "ERROR: sbatch failed with exit status $status."
        return "$status"
    fi
}

usage() {
    cat <<'EOF'
Usage: ./run_wod_comparison.bash --start YYYYMMDD --end YYYYMMDD

Submit WOD-vs-ROMS validation for inclusive hindcast day labels. The script
uses postprocessed ROMS data from $CAWO_POST/ocean3d and submits the workflow
to Slurm.

Environment overrides:
  IHT_SETUP_ENV          Setup script (default: $HOME/inacawo-iht/setup_env.bash)
  IHT_SLURM_PARTITION    Slurm partition (default: DEV1)
EOF
}

START_DATE=""
END_DATE=""
while (($#)); do
    case "$1" in
        --start)
            (($# >= 2)) || { echo "ERROR: --start requires YYYYMMDD." >&2; exit 2; }
            START_DATE="$2"
            shift 2
            ;;
        --end)
            (($# >= 2)) || { echo "ERROR: --end requires YYYYMMDD." >&2; exit 2; }
            END_DATE="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ -z "$START_DATE" || -z "$END_DATE" ]]; then
    echo "ERROR: both --start and --end are required." >&2
    usage >&2
    exit 2
fi

valid_date() {
    [[ "$1" =~ ^[0-9]{8}$ ]] || return 1
    local normalized
    normalized="$(date -d "${1:0:4}-${1:4:2}-${1:6:2}" +%Y%m%d 2>/dev/null)" || return 1
    [[ "$normalized" == "$1" ]]
}

if ! valid_date "$START_DATE" || ! valid_date "$END_DATE"; then
    echo "ERROR: dates must be valid calendar dates in YYYYMMDD format." >&2
    exit 2
fi
if [[ "$START_DATE" > "$END_DATE" ]]; then
    echo "ERROR: --start must be earlier than or equal to --end." >&2
    exit 2
fi

SETUP_ENV="${IHT_SETUP_ENV:-${HOME}/inacawo-iht/setup_env.bash}"
if [[ ! -f "$SETUP_ENV" ]]; then
    echo "ERROR: Inacawo-IHT environment setup not found: $SETUP_ENV" >&2
    exit 1
fi
stage_start "Load environment"
log "Loading environment from: $SETUP_ENV"
source "$SETUP_ENV"
log "Environment loaded."
stage_finish "SUCCESS"

stage_start "Validate inputs and prepare output directories"
WOD_FILE="${IHT_WOD_FILE:-/scratch/cawohdcst/data/hindcast_comparison/WOD_comparison/1995_2014/ocldb1786200299.1695566_CTD.nc}"
ROMS_DIR="${CAWO_POST:?CAWO_POST was not set by setup_env.bash}/ocean3d"
OUTPUT_BASE="${CAWO_HINDCAST_BASE:?CAWO_HINDCAST_BASE was not set by setup_env.bash}/validation/wod_comparison"
RUN_DIR="${OUTPUT_BASE}/${START_DATE}_${END_DATE}"
LOG_DIR="${RUN_DIR}/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="${LOG_DIR}/launcher_${START_DATE}_${END_DATE}_$(date '+%Y%m%d_%H%M%S').log"

log "Run range: ${START_DATE} through ${END_DATE}"
log "WOD input: $WOD_FILE"
log "ROMS input: $ROMS_DIR"
log "Run output: $RUN_DIR"
log "Launcher log: $LOG_FILE"

if [[ ! -f "$WOD_FILE" ]]; then
    echo "ERROR: WOD input file not found: $WOD_FILE" >&2
    exit 1
fi
if [[ ! -d "$ROMS_DIR" ]]; then
    echo "ERROR: Postprocessed ROMS ocean3d directory not found: $ROMS_DIR" >&2
    exit 1
fi
if ! command -v sbatch >/dev/null 2>&1; then
    echo "ERROR: sbatch is unavailable; run this entrypoint on a Slurm login node." >&2
    exit 1
fi
stage_finish "SUCCESS"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PARTITION="${IHT_SLURM_PARTITION:-DEV1}"
SLURM_LOG="${LOG_DIR}/wod_comparison_%j.log"
SLURM_ERROR_LOG="${LOG_DIR}/wod_comparison_%j.err"

log "Submitting Slurm job to partition $PARTITION."
log "Slurm log pattern: $SLURM_LOG"
log "Slurm error log pattern: $SLURM_ERROR_LOG"
stage_start "Submit Slurm job"
submit_job
stage_finish "SUCCESS"
