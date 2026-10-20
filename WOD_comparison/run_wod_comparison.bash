#!/usr/bin/env bash
set -eo pipefail

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
source "$SETUP_ENV"

WOD_FILE="/home/cawohdcst/WOD_comparison/1995_2014/ocldb1786200299.1695566_CTD.nc"
ROMS_DIR="${CAWO_POST:?CAWO_POST was not set by setup_env.bash}/ocean3d"
OUTPUT_BASE="${CAWO_HINDCAST_BASE:?CAWO_HINDCAST_BASE was not set by setup_env.bash}/wod_comparison"
RUN_DIR="${OUTPUT_BASE}/${START_DATE}_${END_DATE}"

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

mkdir -p "$RUN_DIR/logs"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PARTITION="${IHT_SLURM_PARTITION:-DEV1}"

sbatch \
    --partition="$PARTITION" \
    --job-name="wod_${START_DATE}_${END_DATE}" \
    --output="${RUN_DIR}/logs/wod_comparison_%j.log" \
    --export="ALL,IHT_WOD_START=${START_DATE},IHT_WOD_END=${END_DATE},IHT_SETUP_ENV=${SETUP_ENV}" \
    "$SCRIPT_DIR/slurm_extract_roms2wod.bash"
