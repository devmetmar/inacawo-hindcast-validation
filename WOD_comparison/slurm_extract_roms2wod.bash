#!/usr/bin/env bash
#SBATCH --job-name=wod_comparison
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --exclusive
#SBATCH --mem=230G
#SBATCH --time=300:00
#SBATCH --output=log.txt

set -eo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SETUP_ENV="${IHT_SETUP_ENV:-${HOME}/inacawo-iht/setup_env.bash}"

if [[ ! -f "$SETUP_ENV" ]]; then
    echo "ERROR: Inacawo-IHT environment setup not found: $SETUP_ENV" >&2
    exit 1
fi
source "$SETUP_ENV"

if [[ -z "${IHT_WOD_START:-}" || -z "${IHT_WOD_END:-}" ]]; then
    echo "ERROR: IHT_WOD_START and IHT_WOD_END must be set by run_wod_comparison.bash." >&2
    exit 1
fi

WOD_FILE="/home/cawohdcst/WOD_comparison/1995_2014/ocldb1786200299.1695566_CTD.nc"
ROMS_DIR="${CAWO_POST:?CAWO_POST was not set by setup_env.bash}/ocean3d"
OUTPUT_BASE="${CAWO_HINDCAST_BASE:?CAWO_HINDCAST_BASE was not set by setup_env.bash}/wod_comparison"
RUN_DIR="${OUTPUT_BASE}/${IHT_WOD_START}_${IHT_WOD_END}"
EXTRACTED_DIR="${RUN_DIR}/roms_extracted"
DEPTHMATCHED_DIR="${RUN_DIR}/roms_wod_depthmatched"
COMPARISON_DIR="${RUN_DIR}/comparison_depthmatched"

if [[ ! -f "$WOD_FILE" ]]; then
    echo "ERROR: WOD input file not found: $WOD_FILE" >&2
    exit 1
fi
if [[ ! -d "$ROMS_DIR" ]]; then
    echo "ERROR: Postprocessed ROMS ocean3d directory not found: $ROMS_DIR" >&2
    exit 1
fi

mkdir -p "$EXTRACTED_DIR" "$DEPTHMATCHED_DIR" "$COMPARISON_DIR"

python "$SCRIPT_DIR/extract_postprocessed_roms2wod.py" \
    --start "$IHT_WOD_START" \
    --end "$IHT_WOD_END" \
    --wod-file "$WOD_FILE" \
    --roms-dir "$ROMS_DIR" \
    --output-dir "$EXTRACTED_DIR"

python "$SCRIPT_DIR/match_roms2wod_depths.py" \
    --start "$IHT_WOD_START" \
    --end "$IHT_WOD_END" \
    --wod-file "$WOD_FILE" \
    --roms-extracted-dir "$EXTRACTED_DIR" \
    --output-dir "$DEPTHMATCHED_DIR"

python "$SCRIPT_DIR/compare_wod_roms_depthmatched.py" \
    "$DEPTHMATCHED_DIR" \
    "$COMPARISON_DIR" \
    --start "$IHT_WOD_START" \
    --end "$IHT_WOD_END"

echo "WOD comparison completed: $RUN_DIR"
