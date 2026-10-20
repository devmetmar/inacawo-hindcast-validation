#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Shared processing functions for WRF/ERA5 domain-mean time series.

This module is imported by the variable-specific driver scripts. It is not
intended to be executed directly.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
from glob import glob
from pathlib import Path
from typing import Iterable
import os
import time

import cfgrib
import numpy as np
import pandas as pd
import xarray as xr
import xesmf as xe


@contextmanager
def _exclusive_lock(lock_path: Path, poll_seconds: float = 2.0):
    """Simple filesystem lock, suitable for Linux shared filesystems."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"pid={os.getpid()}\n".encode())
            os.close(fd)
            break
        except FileExistsError:
            print(f"Waiting for lock: {lock_path}", flush=True)
            time.sleep(poll_seconds)
    try:
        yield
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def rh_from_t_tdew(t_kelvin: xr.DataArray, td_kelvin: xr.DataArray) -> xr.DataArray:
    """Calculate relative humidity (%) from temperature and dew point in K."""
    t_c = t_kelvin - 273.15
    td_c = td_kelvin - 273.15
    es = 6.112 * np.exp(17.67 * t_c / (t_c + 243.5))
    e = 6.112 * np.exp(17.67 * td_c / (td_c + 243.5))
    rh = 100.0 * e / es
    rh = rh.clip(min=0.0, max=100.0)
    rh.attrs.update(units="%", long_name="2-m relative humidity")
    return rh


def to_hpa(da: xr.DataArray) -> xr.DataArray:
    """Convert a pressure DataArray to hPa without a full Dask median."""
    units = str(da.attrs.get("units", "")).strip().lower()

    if units in {"pa", "pascal", "pascals"}:
        factor = 0.01
    elif units in {"hpa", "hectopascal", "hectopascals", "mbar", "mb"}:
        factor = 1.0
    else:
        sample = da
        if "time" in sample.dims:
            sample = sample.isel(time=0)
        for dim in ("ROW", "COL", "lat", "lon"):
            if dim in sample.dims and sample.sizes[dim] > 20:
                sample = sample.isel({dim: slice(None, None, 20)})
        median = float(np.nanmedian(sample.load().values))
        factor = 0.01 if median > 2000.0 else 1.0

    out = da * factor
    out.attrs = dict(da.attrs)
    out.attrs["units"] = "hPa"
    return out


def open_wrf_year(
    wrf_dir: str,
    year: int,
    wrf_variable: str,
    start_time: pd.Timestamp | None = None,
    end_time: pd.Timestamp | None = None,
) -> xr.Dataset:
    """Open postprocessed WRF 2-D files for a year, limited to requested days."""
    if start_time is not None and end_time is not None:
        year_start = pd.Timestamp(year=year, month=1, day=1)
        year_end = pd.Timestamp(year=year + 1, month=1, day=1)
        range_start = max(start_time, year_start).normalize()
        range_end = min(end_time, year_end)
        if range_start >= range_end:
            raise ValueError(f"Requested date range does not overlap year {year}")

        last_day = (range_end - pd.Timedelta(nanoseconds=1)).normalize()
        patterns = (
            f"{wrf_dir}/f{day:%Y%m%d}/inacawo_hindcast_wrf2d_{year}-*.nc"
            for day in pd.date_range(range_start, last_day, freq="D")
        )
        files = sorted(filename for pattern in patterns for filename in glob(pattern))
        pattern = f"{wrf_dir}/fYYYYMMDD/inacawo_hindcast_wrf2d_{year}-*.nc within requested dates"
    else:
        pattern = f"{wrf_dir}/f{year}*/inacawo_hindcast_wrf2d_{year}-*.nc"
        files = sorted(glob(pattern))

    if not files:
        raise FileNotFoundError(f"No WRF files found with pattern: {pattern}")

    print(f"{year}: opening {len(files)} WRF files for requested days", flush=True)

    def select_required_wrf_data(dataset: xr.Dataset) -> xr.Dataset:
        names = [
            name
            for name in (wrf_variable, "TSTEP", "ROW", "COL")
            if name in dataset
        ]
        return dataset[names]

    ds = xr.open_mfdataset(
        files,
        combine="by_coords",
        preprocess=select_required_wrf_data,
        data_vars="minimal",
        coords="minimal",
        compat="override",
    )

    if wrf_variable not in ds:
        ds.close()
        raise KeyError(f"WRF variable {wrf_variable!r} was not found for {year}")
    if "TSTEP" not in ds:
        ds.close()
        raise KeyError("WRF dataset does not contain TSTEP")

    time_values = pd.to_datetime(ds["TSTEP"].values, unit="s", origin="unix")
    ds = ds.assign_coords(time=("TSTEP", time_values)).swap_dims({"TSTEP": "time"})
    ds = ds.sel(time=slice(f"{year}-01-01", f"{year}-12-31T23:59:59"))

    if ds.sizes.get("time", 0) == 0:
        ds.close()
        raise ValueError(f"No WRF time records remain after selecting year {year}")
    return ds


def _open_required_era5_variables(grib_file: str, required: Iterable[str]) -> xr.Dataset:
    """Extract requested variables from any cfgrib hypercube in one GRIB file."""
    required = tuple(required)
    found: dict[str, xr.DataArray] = {}

    for cube in cfgrib.open_datasets(grib_file):
        for variable in required:
            if variable in cube.data_vars and variable not in found:
                found[variable] = cube[variable]

    missing = [variable for variable in required if variable not in found]
    if missing:
        raise KeyError(f"ERA5 variable(s) {missing} not found in {grib_file}")

    return xr.Dataset(found)


def open_era5_year(
    era5_root: str,
    year: int,
    required: tuple[str, ...],
    start_time: pd.Timestamp | None = None,
    end_time: pd.Timestamp | None = None,
) -> xr.Dataset:
    """Open required ERA5 variables for a year, limited to requested times."""
    if start_time is not None and end_time is not None:
        year_start = pd.Timestamp(year=year, month=1, day=1)
        year_end = pd.Timestamp(year=year + 1, month=1, day=1)
        range_start = max(start_time, year_start).normalize()
        range_end = min(end_time, year_end)
        if range_start >= range_end:
            raise ValueError(f"Requested date range does not overlap year {year}")

        last_day = (range_end - pd.Timedelta(nanoseconds=1)).normalize()
        patterns = (
            f"{era5_root}/era5_{day:%Y%m%d}*/era5_surface_part*.grib"
            for day in pd.date_range(range_start, last_day, freq="D")
        )
        files = sorted(filename for pattern in patterns for filename in glob(pattern))
        pattern = f"{era5_root}/era5_YYYYMMDD*/era5_surface_part*.grib within requested dates"
    else:
        pattern = f"{era5_root}/era5_{year}*/era5_surface_part*.grib"
        files = sorted(glob(pattern))

    if not files:
        raise FileNotFoundError(f"No ERA5 files found with pattern: {pattern}")

    print(f"{year}: found {len(files)} ERA5 files for requested days", flush=True)
    pieces = []
    for filename in files:
        print(f"{year}: opening {filename}", flush=True)
        piece = _open_required_era5_variables(filename, required)
        if start_time is not None and end_time is not None:
            piece = piece.sel(
                time=slice(
                    start_time,
                    end_time - pd.Timedelta(nanoseconds=1),
                )
            )
            if piece.sizes.get("time", 0) == 0:
                piece.close()
                continue
        pieces.append(piece)

    if not pieces:
        raise ValueError(
            f"No ERA5 time records found for {year} within the requested date range"
        )

    ds = xr.concat(pieces, dim="time", compat="override", coords="minimal")
    ds = ds.sortby("time")

    _, unique_indices = np.unique(ds["time"].values, return_index=True)
    ds = ds.isel(time=np.sort(unique_indices))

    rename = {}
    if "latitude" in ds.dims:
        rename["latitude"] = "lat"
    if "longitude" in ds.dims:
        rename["longitude"] = "lon"
    if rename:
        ds = ds.rename(rename)

    if "lat" not in ds.coords or "lon" not in ds.coords:
        ds.close()
        raise KeyError("ERA5 dataset must contain latitude/longitude coordinates")

    if ds["lat"].values[0] > ds["lat"].values[-1]:
        ds = ds.sortby("lat")
    return ds


def build_regridder(
    ds_era: xr.Dataset,
    lat_wrf: xr.DataArray,
    lon_wrf: xr.DataArray,
    weights_file: str | None,
) -> xe.Regridder:
    """Build or reuse one bilinear ERA5-to-WRF xESMF regridder."""
    grid_src = xr.Dataset(
        coords={
            "lat": ("lat", np.asarray(ds_era["lat"].values)),
            "lon": ("lon", np.asarray(ds_era["lon"].values)),
        }
    )
    grid_tgt = xr.Dataset(
        coords={
            "lat": ("lat", np.asarray(lat_wrf.values)),
            "lon": ("lon", np.asarray(lon_wrf.values)),
        }
    )

    if not weights_file:
        return xe.Regridder(grid_src, grid_tgt, "bilinear", reuse_weights=False)

    weights_path = Path(weights_file).expanduser().resolve()
    weights_path.parent.mkdir(parents=True, exist_ok=True)

    if weights_path.exists():
        print(f"Reusing weights: {weights_path}", flush=True)
        return xe.Regridder(
            grid_src,
            grid_tgt,
            "bilinear",
            filename=str(weights_path),
            reuse_weights=True,
        )

    lock_path = Path(str(weights_path) + ".lock")
    with _exclusive_lock(lock_path):
        # Another job may have created the file while this job waited.
        if weights_path.exists():
            print(f"Reusing weights created by another job: {weights_path}", flush=True)
            return xe.Regridder(
                grid_src,
                grid_tgt,
                "bilinear",
                filename=str(weights_path),
                reuse_weights=True,
            )

        print(f"Creating weights: {weights_path}", flush=True)
        return xe.Regridder(
            grid_src,
            grid_tgt,
            "bilinear",
            filename=str(weights_path),
            reuse_weights=False,
        )


def extract_year_series(
    wrf_dir: str,
    era5_root: str,
    year: int,
    wrf_variable: str,
    era5_variables: tuple[str, ...],
    units: str,
    chunk_size: int = 24,
    pressure: bool = False,
    relative_humidity: bool = False,
    weights_file: str | None = None,
    start_time: pd.Timestamp | None = None,
    end_time: pd.Timestamp | None = None,
) -> xr.Dataset:
    """Calculate WRF, ERA5, and WRF-minus-ERA5 domain means for one year."""
    ds_wrf = open_wrf_year(
        wrf_dir,
        year,
        wrf_variable,
        start_time=start_time,
        end_time=end_time,
    )
    ds_era = None
    try:
        ds_era = open_era5_year(
            era5_root,
            year,
            era5_variables,
            start_time=start_time,
            end_time=end_time,
        )
        if start_time is not None and end_time is not None:
            ds_wrf = ds_wrf.where(
                (ds_wrf["time"] >= start_time) & (ds_wrf["time"] < end_time),
                drop=True,
            )
            if ds_wrf.sizes.get("time", 0) == 0:
                raise ValueError(
                    f"No WRF time records found for {year} within the requested date range"
                )

        lat_wrf = ds_wrf["ROW"]
        lon_wrf = ds_wrf["COL"]
        ds_era = ds_era.sel(time=slice(ds_wrf.time.min(), ds_wrf.time.max()))

        regridder = build_regridder(ds_era, lat_wrf, lon_wrf, weights_file)

        wrf_full = ds_wrf[wrf_variable]
        if "LAY" in wrf_full.dims:
            wrf_full = wrf_full.isel(LAY=0)
        if pressure:
            wrf_full = to_hpa(wrf_full)

        wrf_parts: list[xr.DataArray] = []
        era5_parts: list[xr.DataArray] = []
        ntime = wrf_full.sizes["time"]

        for start in range(0, ntime, chunk_size):
            end = min(start + chunk_size, ntime)
            print(f"{year}: chunk {start}:{end} / {ntime}", flush=True)

            wrf_chunk = wrf_full.isel(time=slice(start, end))
            target_times = wrf_chunk["time"]

            # Match ERA5 at each available WRF timestamp; do not interpolate in time.
            if relative_humidity:
                era_native = rh_from_t_tdew(
                    ds_era[era5_variables[0]].sel(time=target_times),
                    ds_era[era5_variables[1]].sel(time=target_times),
                )
            else:
                era_native = ds_era[era5_variables[0]].sel(time=target_times)
                if pressure:
                    era_native = to_hpa(era_native)

            era_native = era_native.transpose("time", "lat", "lon")
            era_regridded = regridder(era_native)
            era_on_wrf = era_regridded.rename({"lat": "ROW", "lon": "COL"})
            era_on_wrf = era_on_wrf.assign_coords(ROW=lat_wrf, COL=lon_wrf)

            wrf_parts.append(
                wrf_chunk.mean(dim=("ROW", "COL"), skipna=True).compute()
            )
            era5_parts.append(
                era_on_wrf.mean(dim=("ROW", "COL"), skipna=True).compute()
            )

        wrf_ts = xr.concat(wrf_parts, dim="time").sortby("time")
        era5_ts = xr.concat(era5_parts, dim="time").sortby("time")
        difference = wrf_ts - era5_ts

        bias = float(difference.mean(skipna=True).values)
        rmse = float(np.sqrt((difference**2).mean(skipna=True).values))
        correlation = float(xr.corr(wrf_ts, era5_ts).values)

        output = xr.Dataset(
            {
                "wrf": wrf_ts.astype("float32"),
                "era5": era5_ts.astype("float32"),
                "difference": difference.astype("float32"),
            }
        )
        output["wrf"].attrs.update(
            units=units,
            long_name=f"Domain-averaged WRF {wrf_variable}",
        )
        output["era5"].attrs.update(
            units=units,
            long_name=f"Domain-averaged ERA5 equivalent of {wrf_variable} after bilinear regridding",
        )
        output["difference"].attrs.update(
            units=units,
            long_name="Domain-averaged WRF minus ERA5",
        )
        output.attrs.update(
            year=int(year),
            wrf_variable=wrf_variable,
            era5_variables=",".join(era5_variables),
            spatial_average="Arithmetic mean over ROW and COL after ERA5 bilinear regridding",
            bias=bias,
            rmse=rmse,
            correlation=correlation,
        )

        print(
            f"{year}: bias={bias:.4f}, RMSE={rmse:.4f}, "
            f"correlation={correlation:.4f}",
            flush=True,
        )
        return output
    finally:
        ds_wrf.close()
        if ds_era is not None:
            ds_era.close()


def run_year_range(
    wrf_dir: str,
    era5_root: str,
    start_year: int,
    end_year: int,
    output_file: str,
    wrf_variable: str,
    era5_variables: tuple[str, ...],
    units: str,
    chunk_size: int = 24,
    pressure: bool = False,
    relative_humidity: bool = False,
    weights_file: str | None = None,
    start_time: pd.Timestamp | None = None,
    end_time: pd.Timestamp | None = None,
) -> None:
    """Process a consecutive year range and save one combined NetCDF file."""
    if end_year < start_year:
        raise ValueError("end_year must be greater than or equal to start_year")
    if chunk_size < 1:
        raise ValueError("chunk_size must be at least 1")

    yearly_results = []
    for year in range(start_year, end_year + 1):
        yearly_results.append(
            extract_year_series(
                wrf_dir=wrf_dir,
                era5_root=era5_root,
                year=year,
                wrf_variable=wrf_variable,
                era5_variables=era5_variables,
                units=units,
                chunk_size=chunk_size,
                pressure=pressure,
                relative_humidity=relative_humidity,
                weights_file=weights_file,
                start_time=start_time,
                end_time=end_time,
            )
        )

    combined = xr.concat(
        yearly_results,
        dim="time",
        data_vars="minimal",
        coords="minimal",
        compat="override",
    ).sortby("time")
    combined.attrs.update(
        start_year=int(start_year),
        end_year=int(end_year),
        number_of_years=int(end_year - start_year + 1),
    )
    if start_time is not None and end_time is not None:
        combined.attrs.update(
            start_date=start_time.strftime("%Y%m%d"),
            end_date=(end_time - pd.Timedelta(days=1)).strftime("%Y%m%d"),
        )

    output_path = Path(output_file).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoding = {
        name: {"zlib": True, "complevel": 4, "dtype": "float32"}
        for name in combined.data_vars
    }
    combined.to_netcdf(output_path, encoding=encoding)
    print(f"Saved NetCDF: {output_path}", flush=True)


def run_date_range(
    wrf_dir: str,
    era5_root: str,
    start_date: str,
    end_date: str,
    output_file: str,
    wrf_variable: str,
    era5_variables: tuple[str, ...],
    units: str,
    chunk_size: int = 24,
    pressure: bool = False,
    relative_humidity: bool = False,
    weights_file: str | None = None,
) -> None:
    """Process an inclusive YYYYMMDD date range and save one NetCDF file."""
    try:
        start = datetime.strptime(start_date, "%Y%m%d")
        end = datetime.strptime(end_date, "%Y%m%d")
    except ValueError as error:
        raise ValueError("start_date and end_date must be valid YYYYMMDD dates") from error

    if end < start:
        raise ValueError("end_date must not be earlier than start_date")

    end_exclusive = end + timedelta(days=1)
    run_year_range(
        wrf_dir=wrf_dir,
        era5_root=era5_root,
        start_year=start.year,
        end_year=end.year,
        output_file=output_file,
        wrf_variable=wrf_variable,
        era5_variables=era5_variables,
        units=units,
        chunk_size=chunk_size,
        pressure=pressure,
        relative_humidity=relative_humidity,
        weights_file=weights_file,
        start_time=pd.Timestamp(start),
        end_time=pd.Timestamp(end_exclusive),
    )
