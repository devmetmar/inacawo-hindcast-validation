#!/usr/bin/env bash
#SBATCH --job-name=wod_comparison
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --exclusive
#SBATCH --mem=230G
#SBATCH --time=300:00
#SBATCH --output=log.txt

set -eo pipefail

TOTAL_START=$SECONDS
STAGE_ORDER=()
declare -A STAGE_DURATIONS=()
declare -A STAGE_RESULTS=()
ACTIVE_STAGE=""
ACTIVE_STAGE_START=0

log() {
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
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

finish_job() {
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
        log "ERROR: Slurm job exited with status $status."
    fi
    log "===== WOD JOB DURATION SUMMARY ====="
    for stage in "${STAGE_ORDER[@]}"; do
        log "SUMMARY: $stage | ${STAGE_RESULTS["$stage"]} | duration=$(format_duration "${STAGE_DURATIONS["$stage"]}")"
    done
    log "SUMMARY: total job duration=$(format_duration "$total_elapsed")"
    if (( status == 0 )); then
        log "SUMMARY: final status=SUCCESS"
    else
        log "SUMMARY: final status=FAILED (exit $status)"
    fi
}

trap 'finish_job "$?"' EXIT

log "Starting WOD comparison Slurm job ${SLURM_JOB_ID:-unknown}."

prepare_run() {
    if [[ -z "${IHT_WOD_START:-}" || -z "${IHT_WOD_END:-}" ]]; then
        log "ERROR: IHT_WOD_START and IHT_WOD_END must be set by run_wod_comparison.bash."
        return 1
    fi
    log "Date range: ${IHT_WOD_START} through ${IHT_WOD_END}"

    WOD_FILE="${IHT_WOD_FILE:?IHT_WOD_FILE was not provided by run_wod_comparison.bash}"
    if [[ -z "${CAWO_POST:-}" || -z "${CAWO_HINDCAST_BASE:-}" ]]; then
        log "ERROR: setup_env.bash did not define CAWO_POST and CAWO_HINDCAST_BASE."
        return 1
    fi
    ROMS_DIR="${CAWO_POST}/ocean3d"
    OUTPUT_BASE="${CAWO_HINDCAST_BASE}/validation/wod_comparison"
    RUN_DIR="${OUTPUT_BASE}/${IHT_WOD_START}_${IHT_WOD_END}"
    ATTEMPT_ID="${SLURM_JOB_ID:?SLURM_JOB_ID is not set}_${SLURM_RESTART_COUNT:-0}"
    ATTEMPT_DIR="${RUN_DIR}/jobs/${ATTEMPT_ID}"
    EXTRACTED_DIR="${ATTEMPT_DIR}/roms_extracted"
    DEPTHMATCHED_DIR="${ATTEMPT_DIR}/roms_wod_depthmatched"
    COMPARISON_DIR="${ATTEMPT_DIR}/comparison_depthmatched"

    log "WOD input: $WOD_FILE"
    log "ROMS input: $ROMS_DIR"
    log "Run output root: $RUN_DIR"
    log "This job's output: $ATTEMPT_DIR"
    if [[ ! -f "$WOD_FILE" ]]; then
        log "ERROR: WOD input file not found: $WOD_FILE"
        return 1
    fi
    log "WOD input file exists."
    if [[ ! -d "$ROMS_DIR" ]]; then
        log "ERROR: Postprocessed ROMS ocean3d directory not found: $ROMS_DIR"
        return 1
    fi
    log "ROMS input directory exists."

    if ! mkdir -p "$EXTRACTED_DIR" "$DEPTHMATCHED_DIR" "$COMPARISON_DIR"; then
        log "ERROR: Could not create one or more output directories."
        return 1
    fi
    log "Fresh output directories are ready for job $ATTEMPT_ID."
}

extract_profiles() {
    python -u "$SCRIPT_DIR/extract_postprocessed_roms2wod.py" \
        --start "$IHT_WOD_START" \
        --end "$IHT_WOD_END" \
        --wod-file "$WOD_FILE" \
        --roms-dir "$ROMS_DIR" \
        --output-dir "$EXTRACTED_DIR"
}

match_depths() {
    python -u "$SCRIPT_DIR/match_roms2wod_depths.py" \
        --start "$IHT_WOD_START" \
        --end "$IHT_WOD_END" \
        --wod-file "$WOD_FILE" \
        --roms-extracted-dir "$EXTRACTED_DIR" \
        --output-dir "$DEPTHMATCHED_DIR"

    local matched_files=("$DEPTHMATCHED_DIR"/roms2wod_depthmatch_*.nc)
    if [[ ! -f "${matched_files[0]}" ]]; then
        log "ERROR: depth matching produced no valid cast files. The comparison stage cannot run."
        log "Check the matcher summary above; casts may have been skipped because extracted ROMS profiles contained only fill values."
        return 1
    fi
    log "Depth matching produced ${#matched_files[@]} valid cast files."
}

compare_results() {
    python -u "$SCRIPT_DIR/compare_wod_roms_depthmatched.py" \
        "$DEPTHMATCHED_DIR" \
        "$COMPARISON_DIR" \
        --start "$IHT_WOD_START" \
        --end "$IHT_WOD_END"
}

stage_start "Load environment"
if [[ -z "${IHT_WOD_SCRIPT_DIR:-}" || ! -d "$IHT_WOD_SCRIPT_DIR" ]]; then
    log "ERROR: WOD comparison script directory not found: ${IHT_WOD_SCRIPT_DIR:-not set}"
    exit 1
fi
SCRIPT_DIR="$IHT_WOD_SCRIPT_DIR"
log "Using WOD script directory: $SCRIPT_DIR"
SETUP_ENV="${IHT_SETUP_ENV:-${HOME}/inacawo-iht/setup_env.bash}"
if [[ ! -f "$SETUP_ENV" ]]; then
    log "ERROR: Inacawo-IHT environment setup not found: $SETUP_ENV"
    exit 1
fi
log "Loading environment from: $SETUP_ENV"
source "$SETUP_ENV"
log "Environment loaded."
stage_finish "SUCCESS"

stage_start "Validate inputs and prepare output directories"
prepare_run
stage_finish "SUCCESS"

stage_start "Extract ROMS profiles at WOD casts"
extract_profiles
stage_finish "SUCCESS"

stage_start "Match ROMS and WOD depths"
match_depths
stage_finish "SUCCESS"

stage_start "Generate WOD comparison results"
compare_results
stage_finish "SUCCESS"

log "WOD comparison completed. Results: $ATTEMPT_DIR"
