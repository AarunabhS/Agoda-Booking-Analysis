"""Reproducible booking analysis; one row is one booking."""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

SHEETS = [f'City_{letter}' for letter in 'ABCDE']
REQUIRED = ['booking_date', 'checkin_date', 'checkout_date', 'ADR_USD',
            'city_id', 'star_rating', 'accommodation_type_name']
BUCKETS = ['Same day', '1–2 days', '3–4 days', '5–14 days', '15–29 days', '30+ days']


def demo_data(seed=42, rows=1000):
    """Synthetic data for smoke testing, never evidence about Agoda."""
    rng = np.random.default_rng(seed)
    booked = pd.Timestamp('2023-08-01') + pd.to_timedelta(rng.integers(0, 153, rows), unit='D')
    checkin = booked + pd.to_timedelta(rng.integers(0, 61, rows), unit='D')
    return pd.DataFrame({
        'booking_date': booked, 'checkin_date': checkin,
        'checkout_date': checkin + pd.to_timedelta(rng.integers(1, 8, rows), unit='D'),
        'ADR_USD': rng.lognormal(4.5, 0.5, rows).round(2),
        'city_id': rng.choice(SHEETS, rows), 'star_rating': rng.integers(1, 6, rows),
        'accommodation_type_name': rng.choice(['Hotel', 'Hostel', 'Resort'], rows),
    })


def load_workbook(path):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f'Workbook not found: {path}. Supply --input PATH or use --demo.')
    with pd.ExcelFile(path) as workbook:
        missing = set(SHEETS) - set(workbook.sheet_names)
        if missing:
            raise ValueError(f'Missing sheets: {", ".join(sorted(missing))}')
        frames = []
        for sheet in SHEETS:
            frame = pd.read_excel(workbook, sheet_name=sheet)
            frame.columns = frame.columns.astype(str).str.strip()
            frame = frame.rename(columns={'accommadation_type_name': 'accommodation_type_name'})
            if frame.columns.duplicated().any():
                raise ValueError(f'{sheet}: duplicate column names after normalization')
            missing_columns = set(REQUIRED) - set(frame.columns)
            if missing_columns:
                raise ValueError(f'{sheet}: missing columns: {", ".join(sorted(missing_columns))}')
            frame['source_city'] = sheet
            frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def prepare_data(raw):
    frame = raw.copy()
    missing = set(REQUIRED) - set(frame.columns)
    if missing:
        raise ValueError(f'Missing columns: {", ".join(sorted(missing))}')
    for column in REQUIRED[:3]:
        frame[column] = pd.to_datetime(frame[column], errors='coerce').dt.normalize()
    for column in ['ADR_USD', 'star_rating']:
        frame[column] = pd.to_numeric(frame[column], errors='coerce')
    for column in ['city_id', 'accommodation_type_name']:
        frame[column] = frame[column].replace(r'^\s*$', pd.NA, regex=True)
    valid = (frame[REQUIRED].notna().all(axis=1)
             & np.isfinite(frame['ADR_USD']) & (frame['ADR_USD'] > 0)
             & frame['star_rating'].between(0, 5)
             & (frame['checkin_date'] >= frame['booking_date'])
             & (frame['checkout_date'] > frame['checkin_date']))
    audit = {'input_rows': len(frame), 'excluded_rows': int((~valid).sum()), 'valid_rows': int(valid.sum())}
    frame = frame.loc[valid].copy()
    if frame.empty:
        raise ValueError('No valid bookings remain after checking dates, rates, and required fields.')
    frame['lead_time'] = (frame['checkin_date'] - frame['booking_date']).dt.days
    frame['length_of_stay'] = (frame['checkout_date'] - frame['checkin_date']).dt.days
    frame['lead_time_bucket'] = pd.cut(frame['lead_time'], [0, 1, 3, 5, 15, 30, np.inf],
                                      labels=BUCKETS, right=False)
    frame['booking_month'] = frame['booking_date'].dt.to_period('M').astype(str)
    return frame, audit


def summarize(frame):
    def grouped(column):
        return frame.groupby(column, observed=True).agg(
            bookings=('ADR_USD', 'size'), average_adr=('ADR_USD', 'mean'),
            average_lead_time=('lead_time', 'mean'))
    tables = {name: grouped(column) for name, column in {
        'daily': 'booking_date', 'monthly': 'booking_month', 'cities': 'city_id',
        'accommodation': 'accommodation_type_name', 'stars': 'star_rating',
        'lead_time': 'lead_time_bucket'}.items()}
    tables['lead_time'] = tables['lead_time'].reindex(BUCKETS)
    tables['lead_time']['bookings'] = tables['lead_time']['bookings'].fillna(0).astype(int)
    return tables


def make_plots(tables, label='Workbook data'):
    import matplotlib.pyplot as plt
    figures = {}
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    tables['daily']['bookings'].plot(ax=axes[0], title=f'Bookings by booking date — {label}')
    tables['daily']['average_adr'].plot(ax=axes[1], color='tab:orange', title='Mean booked ADR')
    axes[0].set_ylabel('Bookings'); axes[1].set_ylabel('USD')
    fig.tight_layout(); figures['daily_trends'] = fig
    for name in ['monthly', 'cities', 'accommodation', 'stars', 'lead_time']:
        fig, axes = plt.subplots(1, 2, figsize=(12, 4))
        tables[name]['bookings'].plot.bar(ax=axes[0], title='Booking count')
        tables[name]['average_adr'].plot.bar(ax=axes[1], title='Mean booked ADR', color='tab:orange')
        axes[0].set_ylabel('Bookings'); axes[1].set_ylabel('USD')
        fig.suptitle(f'{name.replace("_", " ").title()} — {label}')
        fig.tight_layout(); figures[name] = fig
    return figures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--input', type=Path, help='Excel workbook with City_A through City_E sheets')
    source.add_argument('--demo', action='store_true', help='Use explicitly synthetic demo bookings')
    parser.add_argument('--output', type=Path, default=Path('outputs'))
    args = parser.parse_args()
    try:
        raw = demo_data() if args.demo else load_workbook(args.input)
        frame, audit = prepare_data(raw)
    except (ValueError, FileNotFoundError) as error:
        parser.error(str(error))
    import json
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    tables = summarize(frame)
    label = 'SYNTHETIC DEMO' if args.demo else 'Workbook data'
    output = args.output / ('demo' if args.demo else 'workbook')
    output.mkdir(parents=True, exist_ok=True)
    for name, table in tables.items():
        table.to_csv(output / f'{name}.csv')
    for name, figure in make_plots(tables, label).items():
        figure.savefig(output / f'{name}.png', dpi=150)
        plt.close(figure)
    audit['source'] = label
    (output / 'data_quality.json').write_text(json.dumps(audit, indent=2) + '\n')
    print(f'{label}: {audit["valid_rows"]} valid bookings, {audit["excluded_rows"]} excluded. Results: {output}')


if __name__ == '__main__':
    main()
