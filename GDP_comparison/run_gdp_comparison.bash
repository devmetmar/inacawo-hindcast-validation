#!/usr/bin/env bash
set -euo pipefail

TOTAL_START=$SECONDS
STAGE_ORDER=()
STAGE_DURATIONS=()
STAGE_RESULTS=()
ACTIVE_STAGE=""
ACTIVE_STAGE_START=0
LOG_FILE=""

usage() {
    echo "Usage: $0 --start YYYYMMDD --end YYYYMMDD" >&2
}

log() {
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

format_duration() {
    local seconds=$1
    printf '%02d:%02d:%02d' \
        "$((seconds / 3600))" \
        "$(((seconds % 3600) / 60))" \
        "$((seconds % 60))"
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
    STAGE_DURATIONS+=("$elapsed")
    STAGE_RESULTS+=("$result")
    log "STAGE END: $ACTIVE_STAGE | $result | duration=$(format_duration "$elapsed")"
    ACTIVE_STAGE=""
}

finish_launcher() {
    local status=$1
    local total_elapsed=$((SECONDS - TOTAL_START))
    local stage_total=0
    local i
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

    log "===== GDP COMPARISON DURATION SUMMARY ====="
    for i in "${!STAGE_ORDER[@]}"; do
        log "SUMMARY: ${STAGE_ORDER[$i]} | ${STAGE_RESULTS[$i]} | duration=$(format_duration "${STAGE_DURATIONS[$i]}")"
        stage_total=$((stage_total + STAGE_DURATIONS[$i]))
    done
    log "SUMMARY: total recorded stage duration=$(format_duration "$stage_total")"
    log "SUMMARY: total launcher duration=$(format_duration "$total_elapsed")"
    if (( status == 0 )); then
        log "SUMMARY: final status=SUCCESS"
    else
        log "SUMMARY: final status=FAILED (exit $status)"
    fi
}

start_date=""
end_date=""
while (($#)); do
    case "$1" in
        --start)
            (($# >= 2)) || { usage; exit 2; }
            start_date=$2
            shift 2
            ;;
        --end)
            (($# >= 2)) || { usage; exit 2; }
            end_date=$2
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage
            exit 2
            ;;
    esac
done

if [[ -z "$start_date" || -z "$end_date" ]]; then
    usage
    exit 2
fi

validate_date() {
    local value=$1
    [[ "$value" =~ ^[0-9]{8}$ ]] || return 1
    [[ "$(date -d "${value:0:4}-${value:4:2}-${value:6:2}" +%Y%m%d 2>/dev/null)" == "$value" ]]
}

if ! validate_date "$start_date" || ! validate_date "$end_date"; then
    echo "Dates must be valid calendar dates in YYYYMMDD format." >&2
    exit 2
fi
if [[ "$start_date" > "$end_date" ]]; then
    echo "--start must be on or before --end." >&2
    exit 2
fi

setup_env="$HOME/inacawo-iht/setup_env.bash"
if [[ ! -f "$setup_env" ]]; then
    echo "Environment bootstrap not found: $setup_env" >&2
    exit 1
fi
setup_start=$SECONDS
source "$setup_env"

if [[ -z "${CAWO_POST:-}" ]]; then
    echo "CAWO_POST is not set after loading setup_env.bash." >&2
    exit 1
fi
if [[ -z "${CAWO_HINDCAST_BASE:-}" ]]; then
    echo "CAWO_HINDCAST_BASE is not set after loading setup_env.bash." >&2
    exit 1
fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
post_root="$CAWO_POST/ocean3d"
gdp_input_root="/scratch/cawohdcst/data/hindcast_comparison/GDP_comparison"
result_root="$CAWO_HINDCAST_BASE/validation"
run_id="$start_date-$end_date"
extracted_root="$result_root/extracted/$run_id"
comparison_out="$result_root/comparison_plots/$run_id"
log_dir="$result_root/logs"

mkdir -p "$log_dir"
LOG_FILE="$log_dir/gdp_comparison_${run_id}_$(date '+%Y%m%d_%H%M%S').log"
exec > >(tee -a "$LOG_FILE") 2>&1
trap 'finish_launcher "$?"' EXIT

STAGE_ORDER+=("Load environment")
STAGE_DURATIONS+=("$((SECONDS - setup_start))")
STAGE_RESULTS+=("SUCCESS")
log "STAGE: Load environment | SUCCESS | duration=$(format_duration "${STAGE_DURATIONS[0]}")"
log "Run range: $start_date through $end_date"
log "GDP input: $gdp_input_root"
log "ROMS input: $post_root"
log "Result directory: $result_root"
log "Launcher log: $LOG_FILE"

stage_start "Validate ROMS input"
if [[ ! -d "$post_root" ]]; then
    echo "Postprocessed ocean3d directory not found: $post_root" >&2
    exit 1
fi
stage_finish "SUCCESS"

start_year=$((10#${start_date:0:4}))
end_year=$((10#${end_date:0:4}))
years=()

for ((year_num = start_year; year_num <= end_year; year_num++)); do
    year=$(printf '%04d' "$year_num")
    year_start="${year}0101"
    year_end="${year}1231"
    [[ "$year_num" -ne "$start_year" ]] || year_start=$start_date
    [[ "$year_num" -ne "$end_year" ]] || year_end=$end_date

    gdp_file="$gdp_input_root/$year/drifter_6h_$year.nc"
    stage_start "Extract GDP and ROMS for $year"
    if [[ ! -f "$gdp_file" ]]; then
        echo "GDP input file not found: $gdp_file" >&2
        exit 1
    fi

    python "$script_dir/extract_roms2gdp_postprocessed.py" \
        --start "$year_start" \
        --end "$year_end" \
        --post-root "$post_root" \
        --gdp-file "$gdp_file" \
        --out-dir "$extracted_root/$year"
    stage_finish "SUCCESS"
    years+=("$year")
done

stage_start "Generate comparison plots"
python "$script_dir/drf_comparison_drogued.py" \
    "$extracted_root" \
    "$comparison_out" \
    --years "${years[@]}"
stage_finish "SUCCESS"
