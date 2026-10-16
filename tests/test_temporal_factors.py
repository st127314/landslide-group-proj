import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"  # pipeline modules live in scripts/
if not (SCRIPTS / "gee_landslide_factors.py").exists():
    # The Earth Engine extraction scripts are private and not part of the public repository.
    raise unittest.SkipTest("private pipeline scripts are not available in this checkout")
sys.path.insert(0, str(SCRIPTS))
"""Offline regression checks; no authentication, downloads, or exports."""
import csv
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from ee.apitestcase import ApiTestCase
import gee_landslide_factors as factors


class DateTests(unittest.TestCase):
    def test_day_first_and_local_midnight(self):
        self.assertEqual(factors.normalize_event_date({'date_parsed': '2/10/2009'}),
                         ('2009-10-02', '2009-10-02T00:00:00+07:00'))
        self.assertEqual(factors.normalize_event_date({'DATE': '2/10/2009 7:00'})[1],
                         '2009-10-02T00:00:00+07:00')

    def test_invalid_dates_fail(self):
        for value in ['', '31/2/2020', 'not a date']:
            with self.assertRaises(ValueError):
                factors.normalize_event_date({'date_parsed': value})

    def test_current_inventory_dates_are_parseable_and_after_srtm(self):
        features = json.loads(factors.landslide_events_path.read_text())['features']
        for feature in features:
            day, _ = factors.normalize_event_date(feature['properties'])
            self.assertGreater(day, '2000-02-22')

    def test_missing_pixels_retained_and_rainfall_excluded(self):
        row = {'event_date':'2020-01-01', 'event_cutoff':'2020-01-01T00:00:00+07:00',
               'Event_ID':'a', 'land_cover_year':2019, 'sum_d0':100}
        with tempfile.TemporaryDirectory() as temp:
            dest=Path(temp)/'samples.csv'
            factors.save_event_samples([{'properties':row}], ['elevation'],dest)
            with dest.open() as handle:
                result=list(csv.DictReader(handle))[0]
            self.assertEqual(result['NDVI'],'')
            self.assertEqual(result['ndvi_status'],'no_valid_prior_pixel')
            self.assertNotIn('sum_d0',result)

    def test_future_and_out_of_window_observations_rejected(self):
        for observation in ['2020-01-01T00:00:00+07:00','2019-01-01T00:00:00+07:00']:
            row={'event_date':'2020-01-01', 'event_cutoff':'2020-01-01T00:00:00+07:00',
                 'ndvi_observation_ms':datetime.fromisoformat(observation).timestamp()*1000,
                 'NDVI':0.5,'land_cover_year':2019}
            with tempfile.TemporaryDirectory() as temp, self.assertRaises(ValueError):
                factors.save_event_samples([{'properties':row}], [],Path(temp)/'samples.csv')

    def test_same_year_landcover_rejected(self):
        row={'event_date':'2020-01-01','land_cover_year':2020}
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(ValueError):
            factors.save_event_samples([{'properties':row}], [],Path(temp)/'samples.csv')

    def test_future_dynamic_world_rejected(self):
        row={'event_date':'2020-01-01', 'event_cutoff':'2020-01-01T00:00:00+07:00',
             'land_cover_year':2019, 'LULC':1, 'land_cover_source':2,
             'land_cover_observation_ms':datetime.fromisoformat(
                 '2020-01-01T01:00:00+07:00').timestamp()*1000}
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(ValueError):
            factors.save_event_samples([{'properties':row}], [],Path(temp)/'samples.csv')

    def test_native_class_codes_keep_source_specific_labels(self):
        rows=[{'event_date':'2020-01-01','land_cover_year':2019,
               'LULC':code,'land_cover_source':source}
              for code,source in [(12,1),(0,2)]]
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'samples.csv'
            factors.save_event_samples([{'properties':row} for row in rows],[],path)
            with path.open() as handle:
                saved=list(csv.DictReader(handle))
            self.assertEqual(saved[0]['land_cover_class_name'],'palm')
            self.assertEqual(saved[0]['land_cover_class_key'],'servir:12')
            self.assertEqual(saved[1]['land_cover_class_name'],'water')
            self.assertEqual(saved[1]['land_cover_class_key'],'dynamic_world:0')

    def test_servir_legend_from_javascript(self):
        self.assertEqual(set(factors.SERVIR_CLASSES),set(range(1,20)))
        self.assertEqual(factors.SERVIR_CLASSES[6],'evergreen')
        self.assertEqual(factors.SERVIR_CLASSES[17],'water')


class GraphTests(ApiTestCase):
    def test_dated_source_profiles(self):
        # A single chunk per event group (landslide, non-landslide) restores
        # the un-batched 3-calls-per-group pattern that this test checks;
        # batching itself is exercised separately in test_batches_large_groups.
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(factors,'initialize_gee'), \
             patch.object(factors,'SAMPLE_CSV', Path(temp)/'samples.csv'), \
             patch.object(factors,'SAMPLE_BATCH_SIZE', 10_000), \
             patch.object(factors.ee.FeatureCollection,'getInfo', return_value={'features':[]}), \
             patch.object(factors,'sample_event_factors', wraps=factors.sample_event_factors) as sample:
            factors.main([])
            self.assertEqual(sample.call_count, 6)
            self.assertFalse(sample.call_args_list[0].kwargs.get('use_merit', False))
            self.assertTrue(sample.call_args_list[2].kwargs['use_merit'])
            self.assertIn(factors.ALOS_EARLIEST_EVENT, sample.call_args_list[0].args[1].serialize())
            self.assertIn(factors.MERIT_EARLIEST_EVENT, sample.call_args_list[2].args[1].serialize())

    def test_batches_large_groups(self):
        # With a small batch size, each event group must be split into
        # multiple sample_by_dem_era calls (one per chunk of the raw events),
        # not just one big call sliced afterwards -- slicing the *output*
        # collection would not reduce Earth Engine's per-request work.
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(factors,'initialize_gee'), \
             patch.object(factors,'SAMPLE_CSV', Path(temp)/'samples.csv'), \
             patch.object(factors,'SAMPLE_BATCH_SIZE', 50), \
             patch.object(factors.ee.FeatureCollection,'getInfo', return_value={'features':[]}), \
             patch.object(factors,'sample_by_dem_era', wraps=factors.sample_by_dem_era) as sample:
            factors.main([])
            self.assertGreater(sample.call_count, 2)

    def test_skips_point_that_fails_every_retry(self):
        # A point that keeps failing getInfo() must not abort the whole batch;
        # fetch_samples_chunk skips it (logging why) and returns the rest.
        calls = []
        def flaky_getInfo(self):
            calls.append(self)
            raise factors.ee.ee_exception.EEException('User memory limit exceeded.')
        feature_list = [{
            'type': 'Feature',
            'geometry': {'type': 'Point', 'coordinates': [100.0, 8.0]},
            'properties': {'inventory_id': i, 'event_date': '2020-01-01',
                           'event_cutoff': '2020-01-01T00:00:00+07:00'},
        } for i in range(4)]
        aoi = factors.ee.Geometry.Rectangle([99, 7, 101, 9])
        srtm, _, _ = factors.dem_sources(aoi)
        layers = factors.build_factor_layers(aoi, srtm)
        with patch.object(factors,'BATCH_RETRY_ATTEMPTS', 2), \
             patch.object(factors,'BATCH_RETRY_BACKOFF_SECONDS', 0), \
             patch.object(factors.ee.FeatureCollection,'getInfo', flaky_getInfo):
            result = factors.fetch_samples_chunk(
                feature_list, 0, len(feature_list), aoi, layers, layers, layers, 1)
        # Every point was attempted individually (and every attempt failed),
        # but fetch_samples_chunk returned an empty list instead of raising.
        self.assertEqual(result, [])
        self.assertGreaterEqual(len(calls), len(feature_list))

    def test_no_default_exports_or_bucket_requirement(self):
        real_sample_by_dem_era = factors.sample_by_dem_era
        captured = []
        def capture(*args, **kwargs):
            result = real_sample_by_dem_era(*args, **kwargs)
            captured.append(result)
            return result
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(factors,'initialize_gee'), patch.object(factors,'EXPORT_BUCKET',''), \
             patch.object(factors,'SAMPLE_CSV', Path(temp)/'samples.csv'), \
             patch.object(factors,'SAMPLE_BATCH_SIZE', 10_000), \
             patch.object(factors.ee.FeatureCollection,'getInfo', return_value={'features':[]}), \
             patch.object(factors,'sample_by_dem_era', side_effect=capture), \
             patch.object(factors.ee.batch.Export.image,'toCloudStorage') as export:
            factors.main([])
            export.assert_not_called()
            graph=captured[0].serialize()
            self.assertIn('ImageCollection.qualityMosaic',graph)
            self.assertNotIn('2024-11-01',graph)

    def test_optional_reference_exports(self):
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(factors,'initialize_gee'), patch.object(factors,'EXPORT_BUCKET','test'), \
             patch.object(factors,'EXPORT_REFERENCE_DATE','2010-01-01'), \
             patch.object(factors,'SAMPLE_CSV', Path(temp)/'samples.csv'), \
             patch.object(factors.ee.FeatureCollection,'getInfo', return_value={'features':[]}), \
             patch.object(factors.ee.batch.Export.image,'toCloudStorage',
                          side_effect=lambda **kw:Mock(id='offline')) as export:
            factors.main(['--export'])
            names=[call.kwargs['description'] for call in export.call_args_list]
            self.assertEqual(names,['landslide_factor_stack_2010-01-01'])  # one combined export


if __name__=='__main__':
    unittest.main()
