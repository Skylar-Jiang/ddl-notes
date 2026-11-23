"""Console entry point launched invisibly by DDL Notes."""
import argparse
from pathlib import Path

from ddl_notes.background_browser import run_job


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--job-dir', type=Path, required=True)
    parser.add_argument('--action', choices=('login', 'sync'), required=True)
    parser.add_argument('--sources', choices=('xiaoya', 'yuketang'), nargs='+', required=True)
    args = parser.parse_args()
    run_job(args.data_dir, args.job_dir, args.action, args.sources)
