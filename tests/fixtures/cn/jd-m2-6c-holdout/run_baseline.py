"""Replay frozen V9 inputs through public CLI only; never import application code."""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unicodedata
import uuid

FIXTURE = Path(__file__).resolve().parent
ROOT = FIXTURE.parents[3]


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def verify(manifest):
    for name, expected in manifest['oracle_files_sha256'].items():
        assert hashlib.sha256((FIXTURE / name).read_bytes()).hexdigest() == expected, name


def cli(*arguments):
    command = [sys.executable, '-m', 'jobsearch_cn', *map(str, arguments)]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, encoding='utf-8')
    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError:
        output = {'unparsed_stdout': result.stdout}
    return {'arguments': list(map(str, arguments)), 'exit_code': result.returncode, 'output': output, 'stderr': result.stderr}


def expect_success(result):
    if result['exit_code']:
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    return result['output']


def get(record, dotted):
    for part in dotted.split('.'):
        record = record[part]
    return record


def put(record, dotted, value):
    parts = dotted.split('.')
    for part in parts[:-1]:
        record = record[part]
    record[parts[-1]] = value


def normalize(text):
    return ''.join(unicodedata.normalize('NFKC', text).casefold().split())


def compare(field, expected, actual):
    if field in ('requirements.skills', 'cities'):
        want, found = set(map(normalize, expected)), set(map(normalize, actual))
        missing, extra = sorted(want - found), sorted(found - want)
        kind = 'wrong' if missing and extra else 'missing' if missing else 'extra' if extra else 'match'
    else:
        want, found = deepcopy(expected), deepcopy(actual)
        if field == 'requirements.graduation' and want and found:
            want['years'] = sorted(want['years'])
            found['years'] = sorted(found['years'])
        kind = 'match' if want == found else 'missing' if found is None else 'extra' if want is None else 'wrong'
        missing, extra = [], []
    return {'type': kind, 'expected': expected, 'actual': actual, 'missing_normalized': missing, 'extra_normalized': extra}


def compare_filter(expected, actual):
    checks = {c['check']: c for c in actual['checks']}
    differences = {name: {'expected': v['result'], 'actual': checks.get(name, {}).get('result')} for name, v in expected['checks'].items() if checks.get(name, {}).get('result') != v['result']}
    return {'verdict_match': expected['verdict'] == actual['verdict'], 'expected_verdict': expected['verdict'], 'actual_verdict': actual['verdict'], 'check_matches': len(expected['checks']) - len(differences), 'check_differences': differences}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', default='master-a70dbc7')
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    manifest = read(FIXTURE / 'oracle-manifest.json')
    verify(manifest)
    if args.verify_only:
        print(json.dumps({'frozen_files_verified': len(manifest['oracle_files_sha256'])}))
        return
    if subprocess.call(['git', 'diff', '--quiet', manifest['base_commit'], '--', 'jobsearch_cn'], cwd=ROOT):
        raise SystemExit('Application differs from frozen base; use a separate comparison runner')
    output_dir = FIXTURE / 'actual' / args.label
    if output_dir.exists():
        raise SystemExit('Actual output exists; never overwrite a baseline')
    run_dir = Path('data') / 'v9-check' / uuid.uuid4().hex
    (ROOT / run_dir).mkdir(parents=True)
    started = datetime.now(timezone.utc).isoformat()
    profiles = {p: Path('tests/fixtures/cn/profile') / p / 'profile.json' for p in ('tech', 'ops')}
    counts = Counter()
    index = []
    for expected_path in sorted(FIXTURE.glob('*.expected.json')):
        expected = read(expected_path)
        source = FIXTURE / expected['fixture']
        stem = source.stem
        parsed = cli('jd', 'parse', source.relative_to(ROOT), '--site', expected['site_argument'], '--save', '--data-dir', run_dir / 'parsed')
        job = expect_success(parsed)['jobs'][0]
        fields = {key: compare(key, f['value'], get(job, key)) for key, f in expected['fields'].items()}
        for comparison in fields.values():
            counts['fields_' + comparison['type']] += 1
        want = set(map(normalize, expected['fields']['requirements.skills']['value']))
        found = set(map(normalize, job['requirements']['skills']))
        counts['skill_expected'] += len(want)
        counts['skill_hit'] += len(want & found)
        counts['skill_extra'] += len(found - want)
        parsed_filters, filter_comparison = {}, {}
        for name, profile in profiles.items():
            result = cli('match', 'filter', job['id'], '--profile', profile, '--data-dir', run_dir / 'parsed')
            actual = expect_success(result)
            parsed_filters[name] = result
            diff = compare_filter(expected['human_match'][name], actual)
            filter_comparison[name] = diff
            counts['parsed_verdict_match'] += diff['verdict_match']
            counts['parsed_check_match'] += diff['check_matches']
        complete = deepcopy(job)
        for key, f in expected['fields'].items():
            put(complete, key, f['value'])
            if f['value'] is None or f['value'] == []:
                complete['evidence'].pop(key, None)
            else:
                complete['evidence'][key] = {'text': f['evidence'], 'method': 'agent'}
        replay_file = run_dir / (stem + '.replay.json')
        write(ROOT / replay_file, complete)
        valid = cli('jd', 'validate', replay_file)
        replay = {'validation': valid}
        if valid['exit_code'] == 0 and valid['output'].get('valid'):
            counts['replay_valid'] += 1
            saved = cli('jd', 'save', replay_file, '--data-dir', run_dir / 'replay')
            expect_success(saved)
            replay['saved'] = saved
            replay['filters'] = {}
            replay['comparison'] = {}
            for name, profile in profiles.items():
                filtered = cli('match', 'filter', complete['id'], '--profile', profile, '--data-dir', run_dir / 'replay')
                actual = expect_success(filtered)
                replay['filters'][name] = filtered
                diff = compare_filter(expected['human_match'][name], actual)
                replay['comparison'][name] = diff
                counts['replay_verdict_match'] += diff['verdict_match']
                counts['replay_check_match'] += diff['check_matches']
        item = {'fixture': expected['fixture'], 'parse': parsed, 'field_comparison': fields, 'filters': parsed_filters, 'filter_comparison': filter_comparison, 'oracle_replay': replay}
        write(output_dir / (stem + '.json'), item)
        index.append({'fixture': expected['fixture'], 'field_matches': sum(v['type'] == 'match' for v in fields.values()), 'differences': {k: v for k, v in fields.items() if v['type'] != 'match'}, 'parsed_match': filter_comparison, 'replay_match': replay.get('comparison', {})})
    verify(manifest)
    summary = {'label': args.label, 'code_commit': manifest['base_commit'], 'fixture_commit_at_run': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(), 'started_at_utc': started, 'finished_at_utc': datetime.now(timezone.utc).isoformat(), 'manifest_sha256': hashlib.sha256((FIXTURE / 'oracle-manifest.json').read_bytes()).hexdigest(), 'frozen_files_unchanged': True, 'counts': dict(counts), 'new_feature_status': {'status': 'unsupported_in_baseline_contract', 'semantic_groups': 15, 'planned_new_check_states': 20, 'note': '新字段与检查尚未在master契约中实现，不把缺字段当作原文unknown或计入旧14字段正确率。'}, 'fixtures': index}
    write(output_dir / 'summary.json', summary)
    print(json.dumps({'counts': dict(counts), 'frozen_files_unchanged': True, 'new_feature_status': 'unsupported_in_baseline_contract'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
