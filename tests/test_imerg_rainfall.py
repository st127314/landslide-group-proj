import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"  # pipeline modules live in scripts/
if not (SCRIPTS / "gee_landslide_factors.py").exists():
    # The Earth Engine extraction scripts are private and not part of the public repository.
    raise unittest.SkipTest("private pipeline scripts are not available in this checkout")
sys.path.insert(0, str(SCRIPTS))
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import gee_imerg_antecedent_rainfall as rainfall


class RainfallTests(unittest.TestCase):
    def test_midnight_cutoff_in_thailand(self):
        local,end,quality=rainfall.event_cutoff({'DATE':'2/10/2009 7:00'})
        self.assertEqual(local.isoformat(),'2009-10-02T00:00:00+07:00')
        self.assertEqual(end.isoformat(),'2009-10-01T17:00:00+00:00')
        self.assertEqual(quality,'start_of_day_proxy')

    def test_non_aligned_timestamp_excludes_future_half_hour(self):
        with patch.object(rainfall,'TIME_MODE','recorded'):
            local,end,_=rainfall.event_cutoff({'DATE':'2/10/2009 7:15'})
            self.assertEqual((local-end).total_seconds(),900)

    def test_inventory_dates_and_window_count(self):
        self.assertEqual(len(rainfall.WINDOWS),33)
        self.assertEqual(len(rainfall.load_events()),6180)

    def series(self,rate=2):
        end=datetime(2020,1,31,tzinfo=timezone.utc)
        rows=[['id','longitude','latitude','time','precipitation']]
        for step in range(1440):
            stamp=int((end-timedelta(minutes=30*(step+1))).timestamp()*1000)
            rows.append([str(step),100,10,stamp,rate])
        return end,rows

    def test_mm_per_hour_integrated_over_half_hours(self):
        end,rows=self.series()
        result=rainfall.accumulate_windows(rows,end)
        for label,hours in rainfall.WINDOWS:
            self.assertEqual(result[f'rain_{label}_mm'],hours*2)
            self.assertEqual(result[f'rain_{label}_coverage_pct'],100)

    def test_missing_interval_not_zero(self):
        end,rows=self.series()
        rows[1][-1]=None
        result=rainfall.accumulate_windows(rows,end)
        self.assertIsNone(result['rain_1h_mm'])
        self.assertEqual(result['rain_1h_coverage_pct'],50)
        self.assertIsNone(result['rain_30d_mm'])

    def test_gap_outside_short_window_does_not_invalidate_it(self):
        end,rows=self.series()
        rows[-1][-1]=-9999
        result=rainfall.accumulate_windows(rows,end)
        self.assertEqual(result['rain_1h_mm'],2)
        self.assertIsNone(result['rain_30d_mm'])

    def test_zero_rain_is_valid_and_cutoff_is_exclusive(self):
        end,rows=self.series(0)
        rows.append(['future',100,10,int(end.timestamp()*1000),1000])
        self.assertEqual(rainfall.accumulate_windows(rows,end)['rain_1h_mm'],0)

    def test_duplicate_timestep_rejected(self):
        end,rows=self.series()
        rows.append(rows[1])
        with self.assertRaises(ValueError):
            rainfall.accumulate_windows(rows,end)

    def test_empty_coverage(self):
        end,_=self.series()
        result=rainfall.accumulate_windows([],end)
        self.assertIsNone(result['rain_1h_mm'])
        self.assertEqual(result['rain_1h_coverage_pct'],0)


if __name__=='__main__':
    unittest.main()
