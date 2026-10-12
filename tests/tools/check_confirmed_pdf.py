"""Isolated local checks; do not write application DB or running Next output."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from app.config import get_settings
from pymongo.uri_parser import parse_uri

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / '_media/fix-confirmed-pdf-20261011-delivery'
WEB = ROOT.parent / 'biblioteca-eclesiastica-web'

def main():
    assert DEST.is_dir() and not (DEST / 'checks.json').exists()
    database = 'biblioteca_fix_confirmed_pdf_20261011'
    assert database != get_settings().mongodb_db
    env = os.environ.copy()
    env.update(MONGODB_URI='mongodb://127.0.0.1:27017', MONGODB_DB=database,
               MEDIA_ROOT=str(DEST / 'test-media'))
    assert all(host in ('127.0.0.1', 'localhost', '::1') for host, _ in parse_uri(env['MONGODB_URI'])['nodelist'])
    checks = []
    def run(command, cwd, label):
        result = subprocess.run(command, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (DEST / f'{label}.log').write_text(result.stdout, encoding='utf-8')
        print(label, result.stdout)
        checks.append({'command': command, 'cwd': str(cwd), 'exit_code': result.returncode, 'log': f'{label}.log'})
    run(['uv', 'run', 'pytest', '--basetemp', str(DEST / 'pytest-temp')], ROOT, 'pytest')
    run(['uv', 'run', 'python', '-m', 'compileall', '-q', 'app', 'tests/tools', 'scripts'], ROOT, 'compileall')
    if '--api-only' in sys.argv:
        (DEST / 'checks.json').write_text(json.dumps({'database': database, 'uri': env['MONGODB_URI'], 'checks': checks}, indent=2), encoding='utf-8')
        assert all(check['exit_code'] == 0 for check in checks)
        return
    # Both known project Next production servers remain untouched. Compile an
    # isolated source copy; dependency junction is read-only during checks.
    copy = DEST / 'web-check'
    assert not copy.exists()
    copy.mkdir()
    for entry in WEB.iterdir():
        if entry.name in ('app', 'components', 'lib', 'public', 'scripts', 'tests'):
            shutil.copytree(entry, copy / entry.name)
        elif entry.is_file() and (entry.suffix in ('.ts', '.mjs', '.json') or entry.name == '.gitignore') and not entry.name.startswith('.env'):
            shutil.copy2(entry, copy / entry.name)
    assert copy.is_dir() and (WEB / 'node_modules').is_dir()
    subprocess.run(['cmd', '/c', 'mklink', '/J', str(copy / 'node_modules'), str(WEB / 'node_modules')], check=True)
    # Generated validation config only: allow the dependency junction inside
    # Turbopack's root. The application's own config and build are untouched.
    config = copy / 'next.config.ts'
    config.write_text(config.read_text(encoding='utf-8').replace('turbopack: {', 'turbopack: {\n    root: "C:/code",', 1), encoding='utf-8')
    run(['npm.cmd', 'run', 'build'], copy, 'npm-build')
    run(['npm.cmd', 'run', 'lint'], copy, 'npm-lint')
    (DEST / 'checks.json').write_text(json.dumps({'database': database, 'uri': env['MONGODB_URI'], 'checks': checks}, indent=2), encoding='utf-8')
    assert all(check['exit_code'] == 0 for check in checks)

if __name__ == '__main__':
    main()
