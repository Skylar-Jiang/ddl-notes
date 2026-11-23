"""Package the complete Windows bundle using ordinary shared read access."""
import argparse
from pathlib import Path
import zipfile


def package(directory, output):
    directory, output = Path(directory), Path(output)
    files = [directory / name for name in ('DDLNotes.exe', 'DDLNotesSync.exe',
                                          'README.md', 'SYNC-SETUP.md', 'TESTING.md')]
    for name in ('browser-helper', 'DDLNotesAutoSync'):
        folder = directory / name
        if not folder.is_dir():
            raise FileNotFoundError(folder)
        files.extend(p for p in folder.rglob('*') if p.is_file())
    temporary = output.with_suffix('.zip.tmp')
    with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(directory).as_posix())
    with zipfile.ZipFile(temporary) as archive:
        if archive.testzip() is not None:
            raise ValueError('ZIP validation failed')
    temporary.replace(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, default=Path(__file__).resolve().parents[1] / 'dist')
    args = parser.parse_args()
    package(args.directory, args.directory / 'DDLNotes-with-course-sync.zip')
    print('Complete Windows bundle packaged and verified.')
