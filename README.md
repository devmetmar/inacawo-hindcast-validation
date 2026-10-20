# InaCAWO hindcast validation

This directory contains three workflows for comparing postprocessed InaCAWO
hindcast data with observational or reanalysis products:

- [GDP comparison](./GDP_comparison/README.md): ROMS currents versus Global
  Drifter Program (GDP) drifters.
- [WOD comparison](./WOD_comparison/README.md): ROMS temperature/salinity
  profiles versus World Ocean Database (WOD) CTD casts.
- [WRF–ERA5 comparison](./WRF_ERA5_comparison/README.md): postprocessed WRF
  surface variables versus ERA5, including optional drift analysis.

Each workflow has its own README with detailed inputs, paths, options, and
outputs. There is no single launcher for all three workflows; run each one
separately for the dates and products it supports.

## Validation period

The GDP and WOD validation datasets available to these workflows cover **January
1995 through December 2014**. To validate a ROMS hindcast against these
observations, the simulation and postprocessing must include the period being
compared within this range. A simulation outside this period cannot be
validated against the available GDP/WOD data.

Use an inclusive date range within `19950101`–`20141231`, for example:

```text
--start 20000101 --end 20001231
```

The WRF–ERA5 workflow uses ERA5 rather than GDP/WOD observations, so its usable
dates also depend on the ERA5 and postprocessed WRF files available at the
configured paths. If running it as part of a validation covering the available
GDP/WOD period, use dates within 1995–2014 and confirm that both WRF and ERA5
inputs exist for those dates.

## Overall pipeline

The workflows use postprocessed ROMS/WRF products; they do not run the model or
generate the postprocessed products themselves. The general sequence is:

1. **Run the hindcast** for the desired validation dates. For comparison with
   the available GDP/WOD observations, keep the selected dates within
   1995–2014.
2. **Postprocess the model output** using the InaCAWO-IHT workflow. GDP and WOD
   read the `ocean3d` product under `$CAWO_POST/ocean3d`; WRF–ERA5 reads
   `wrf2d` under `$CAWO_POST/wrf2d`.
3. **Run one or more comparison workflows** from the corresponding directory.
   The launchers load `$HOME/inacawo-iht/setup_env.bash` and use paths and
   environment variables configured by InaCAWO-IHT.
4. **Review the generated files and logs** in the workflow-specific output
   locations below.

```text
Inacawo_validation/
├── README.md
├── GDP_comparison/
│   ├── run_gdp_comparison.bash
│   ├── extract_roms2gdp_postprocessed.py
│   ├── drf_comparison_drogued.py
│   └── README.md
├── WOD_comparison/
│   ├── run_wod_comparison.bash
│   ├── slurm_extract_roms2wod.bash
│   ├── extract_postprocessed_roms2wod.py
│   ├── match_roms2wod_depths.py
│   ├── compare_wod_roms_depthmatched.py
│   └── README.md
└── WRF_ERA5_comparison/
    ├── slurm_save_wrf_era5_series_array_clean.bash
    ├── save_*_series_clean.py
    ├── wrf_era5_series_common_clean.py
    ├── wrf_era5_drift_analysis.py
    └── README.md
```

## Workflows

### GDP: drifter currents

From a shell with the InaCAWO-IHT environment available, run:

```bash
cd /path/to/Inacawo_validation/GDP_comparison
./run_gdp_comparison.bash --start YYYYMMDD --end YYYYMMDD
```

The date range is inclusive. The launcher processes each year in the range:
it extracts ROMS eastward/northward currents at GDP drifter locations, then
creates per-year and combined comparison plots. It runs directly in the
current shell and does not submit a Slurm job.

ROMS currents are sampled at the nearest grid point and the available model
level closest to 10 m depth. Observation times are matched to the nearest ROMS
time within 12 hours. The comparison retains observations while the drifter is
drogued. GDP input files are expected under
`/scratch/cawohdcst/data/hindcast_comparison/GDP_comparison/YYYY/`. Outputs are
written to the `extracted/` and `comparison_plots/` subdirectories under that
data root.

### WOD: CTD temperature/salinity profiles

From a Slurm login node with InaCAWO-IHT configured, run:

```bash
cd /path/to/Inacawo_validation/WOD_comparison
./run_wod_comparison.bash --start YYYYMMDD --end YYYYMMDD
```

The inclusive date range uses completed hindcast day labels. The launcher
submits one Slurm job, which runs these stages in order:

1. Extract postprocessed ROMS profiles at WOD cast locations and times.
2. Match ROMS and WOD depths within 5 m, without vertical interpolation.
3. Apply WOD quality control and produce comparison statistics and plots.

The WOD input is the configured 1995–2014 CTD NetCDF file. ROMS input is
`$CAWO_POST/ocean3d`. Results, including intermediate extraction and
depth-matched data, comparison output, and Slurm logs, are written under
`$CAWO_HINDCAST_BASE/wod_comparison/<start>_<end>/`.

### WRF–ERA5: surface fields and drift analysis

From a shell with InaCAWO-IHT configured, submit the four-task Slurm array:

```bash
cd /path/to/Inacawo_validation/WRF_ERA5_comparison
./slurm_save_wrf_era5_series_array_clean.bash --start YYYYMMDD --end YYYYMMDD
```

The inclusive date range is used to extract mean sea-level pressure, 10 m
eastward wind (`u10`), 10 m northward wind (`v10`), and 2 m relative humidity
(`rh2`) from postprocessed WRF and compare/regrid against ERA5. The launcher
submits one Slurm array with four tasks. By default it uses the `DEV1`
partition; `IHT_SLURM_PARTITION` can select another partition.

The postprocessed WRF product is `$CAWO_POST/wrf2d`; ERA5 and the bilinear
regridding weights are read from the configured shared paths. The four
compressed NetCDF time-series files and Slurm logs are written under the
`WRF_ERA5_comparison/output/` and `WRF_ERA5_comparison/logs/` directories.
After all extraction tasks finish, drift analysis can be run separately with
`wrf_era5_drift_analysis.py`; see the workflow README for the command and
options. The analysis writes CSV summaries and figures to its selected output
directory.

## Environment and operational notes

- Run the workflows on the InaCAWO-IHT system with the required postprocessed
  products and observation/reanalysis inputs accessible at their configured
  paths.
- GDP and WOD launchers source the InaCAWO-IHT setup script. WOD and WRF–ERA5
  submit jobs through Slurm; run those launchers from a system where `sbatch`
  is available.
- The active Python environment must include each workflow's dependencies.
  These include `numpy`, `pandas`, `xarray`, `matplotlib`, and `scipy`; WOD
  additionally uses `gsw` and `scikit-learn`.
- Check each workflow README before running for its exact data paths, output
  layout, environment overrides, and other requirements.
