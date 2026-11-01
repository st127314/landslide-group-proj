# Antecedent rainfall from IMERG

Run from the project directory:

```bash
python scripts/gee_imerg_antecedent_rainfall.py
```

The separate script reads every point in `data/inventory/landslide_inventory.geojson`,
uses `scripts/service_account/key.json`, and writes
`data/processed/landslide_event_antecedent_rainfall.csv`. It does not alter the conditioning
factor script or its CSV, and it does not submit raster exports. Settings are at
the top of the script; it uses the existing Earth Engine dependency.

The output contains 33 nested accumulated-rainfall totals:

- `rain_1h_mm`, `rain_3h_mm`, `rain_6h_mm`.
- `rain_1d_mm` through `rain_30d_mm`, one column for each duration.

Each total ends at **midnight at the start of the event day in Asia/Bangkok**.
For an event dated 2 October 2009, the cutoff is
`2009-10-02 00:00 +07:00` (`2009-10-01 17:00 UTC`). The 1-hour total covers
23:00–00:00 local time; the 1-day total covers the preceding 24 hours. The event
day is excluded. These are cumulative duration windows, not separate daily lags
and not an exponentially weighted antecedent precipitation index.

`TIME_MODE="start_of_day"` deliberately ignores the inventory's uniform 07:00
values. Rows carry `time_quality=start_of_day_proxy`: short-window totals describe
rainfall before the chosen day boundary, not necessarily before the actual failure
hour. Recorded-time mode is available in the configuration if reliable event times
become available. Non-half-hour cutoffs are rounded down to the last completed
30-minute interval; the shift is recorded explicitly.

Source: [NASA/GPM_L3/IMERG_V07](https://developers.google.com/earth-engine/datasets/catalog/NASA_GPM_L3_IMERG_V07).
The `precipitation` band is a calibrated precipitation rate in **mm/hour**.
The script multiplies each 30-minute rate by **0.5 hours** before summing.
It selects `status=permanent` for retrospective model development. Products are
reprocessed estimates and may have been published after the historical event;
this is not a simulation of real-time data availability.

Sampling uses the native IMERG projection and grid transform (0.1°, about 11 km),
not a 10/30 m resampled product. The satellite estimate represents the grid cell,
not a rain gauge at the event point. The script fetches one 30-day point time
series and computes every window locally, avoiding 33 separate GEE requests.

Every window has a matching `rain_*_coverage_pct` column. Missing, masked,
nonfinite, negative or absent observations make that window's total blank;
observed zero rainfall remains zero. Complete windows need 2, 6, 12, or 48×days
valid half-hour records. Duplicate timestamps stop processing rather than double
counting. Row metadata records source, product status, event/cutoff times and
whether every requested window is complete.

Raw point time series are cached under `data/cache/imerg_cache/`, keyed by dataset,
status, coordinate, dates and sampling grid. Rerunning reuses completed requests;
delete the relevant cache files to refresh them after source revisions. Rows are
written progressively to `.csv.part`; the final CSV replaces the previous output
only after all events finish. Source errors stop the run and preserve the cache.

Use `Event_ID` (plus location/date if IDs are not unique) to join the rainfall CSV
to the conditioning-factor CSV. `event_row` preserves the input feature position.

Checks:

```bash
python -m unittest discover -s tests -p 'test_imerg_rainfall.py'
```
