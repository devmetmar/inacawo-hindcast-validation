#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "Usage: $0 --start YYYYMMDD --end YYYYMMDD" >&2
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
source "$setup_env"

if [[ -z "${CAWO_POST:-}" ]]; then
    echo "CAWO_POST is not set after loading setup_env.bash." >&2
    exit 1
fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
post_root="$CAWO_POST/ocean3d"
gdp_input_root="/scratch/cawohdcst/data/hindcast_comparison/GDP_comparison"
result_root="$HOME/inacawo-hindcast-validation/GDP_comparison"
run_id="$start_date-$end_date"
extracted_root="$result_root/extracted/$run_id"
comparison_out="$result_root/comparison_plots/$run_id"

if [[ ! -d "$post_root" ]]; then
    echo "Postprocessed ocean3d directory not found: $post_root" >&2
    exit 1
fi

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
    years+=("$year")
done

python "$script_dir/drf_comparison_drogued.py" \
    "$extracted_root" \
    "$comparison_out" \
    --years "${years[@]}"
