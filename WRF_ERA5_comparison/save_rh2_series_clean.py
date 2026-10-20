#!/usr/bin/env python3
import argparse
from wrf_era5_series_common_clean import run_date_range

p = argparse.ArgumentParser(description="Save WRF/ERA5 domain-mean 2-m relative-humidity series.")
p.add_argument("wrf_dir")
p.add_argument("era5_root")
p.add_argument("--start", required=True, help="First simulation date (YYYYMMDD, inclusive)")
p.add_argument("--end", required=True, help="Last simulation date (YYYYMMDD, inclusive)")
p.add_argument("output")
p.add_argument("--chunk-size", type=int, default=24)
p.add_argument("--weights-file", default=None)
a = p.parse_args()

run_date_range(
    a.wrf_dir, a.era5_root, a.start, a.end, a.output,
    wrf_variable="RELHUM_2M",
    era5_variables=("t2m", "d2m"),
    units="%",
    chunk_size=a.chunk_size,
    relative_humidity=True,
    weights_file=a.weights_file,
)
