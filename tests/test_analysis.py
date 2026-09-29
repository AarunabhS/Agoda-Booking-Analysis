import tempfile
import unittest
from pathlib import Path

import pandas as pd

from analysis import BUCKETS, SHEETS, demo_data, load_workbook, prepare_data, summarize


class AnalysisTests(unittest.TestCase):
    def test_bucket_boundaries_and_counts(self):
        raw = demo_data(rows=10)
        days = [0, 1, 2, 3, 4, 5, 14, 15, 29, 30]
        raw['checkin_date'] = raw['booking_date'] + pd.to_timedelta(days, unit='D')
        raw['checkout_date'] = raw['checkin_date'] + pd.Timedelta(days=1)
        frame, audit = prepare_data(raw)
        self.assertEqual(frame['lead_time_bucket'].astype(str).tolist(),
                         [BUCKETS[i] for i in [0, 1, 1, 2, 2, 3, 3, 4, 4, 5]])
        self.assertEqual(audit['valid_rows'], 10)
        for table in summarize(frame).values():
            self.assertEqual(table['bookings'].sum(), 10)

    def test_invalid_rows_are_reported(self):
        raw = demo_data(rows=5)
        raw.loc[0, 'ADR_USD'] = float('inf')
        raw.loc[1, 'checkin_date'] = raw.loc[1, 'booking_date'] - pd.Timedelta(days=1)
        raw.loc[2, 'checkout_date'] = raw.loc[2, 'checkin_date']
        raw.loc[3, 'accommodation_type_name'] = ' '
        _, audit = prepare_data(raw)
        self.assertEqual(audit, {'input_rows': 5, 'excluded_rows': 4, 'valid_rows': 1})

    def test_workbook_alias_and_all_cities(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'data.xlsx'
            with pd.ExcelWriter(path) as writer:
                for city in SHEETS:
                    demo_data(rows=3).rename(columns={
                        'accommodation_type_name': 'accommadation_type_name'
                    }).to_excel(writer, sheet_name=city, index=False)
            frame, audit = prepare_data(load_workbook(path))
            self.assertEqual(audit['valid_rows'], 15)
            self.assertEqual(set(frame['source_city']), set(SHEETS))
            with pd.ExcelWriter(path) as writer:
                demo_data(rows=3).to_excel(writer, sheet_name='City_A', index=False)
            with self.assertRaisesRegex(ValueError, 'Missing sheets'):
                load_workbook(path)

    def test_missing_input_and_empty_data_fail_clearly(self):
        with self.assertRaises(FileNotFoundError):
            load_workbook('missing.xlsx')
        with self.assertRaisesRegex(ValueError, 'No valid bookings'):
            prepare_data(demo_data(rows=0))
        with self.assertRaisesRegex(ValueError, 'Missing columns'):
            prepare_data(pd.DataFrame({'ADR_USD': [100]}))

    def test_months_keep_year_and_absent_rates_stay_missing(self):
        raw = demo_data(rows=2)
        raw['booking_date'] = pd.to_datetime(['2023-12-01', '2024-12-01'])
        raw['checkin_date'] = raw['booking_date']
        raw['checkout_date'] = raw['checkin_date'] + pd.Timedelta(days=1)
        tables = summarize(prepare_data(raw)[0])
        self.assertEqual(tables['monthly'].index.tolist(), ['2023-12', '2024-12'])
        self.assertTrue(pd.isna(tables['lead_time'].loc[BUCKETS[-1], 'average_adr']))


if __name__ == '__main__':
    unittest.main()
