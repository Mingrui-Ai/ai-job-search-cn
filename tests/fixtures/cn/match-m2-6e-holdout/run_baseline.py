"""Record the pre-M2-6e master through its CLI after V19's local oracle commit."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from verify_oracle import FIX, FROZEN_NAMES, digest, read, verify

ROOT = FIX.parents[3]
BASE = 'd8ec9adeff7dfc7ade1c8057f468bfc7e7104510'
MANIFEST_HASH = '616aecd87d096684f633874cc26735d9de61d85dac1a2a5128538a28984ae032'


def git(*args, cwd=ROOT):
    return subprocess.check_output(['git', *args], cwd=cwd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True, help='own clean checkout of the frozen master')
    args = parser.parse_args()
    repo = args.repo.resolve()
    assert git('rev-parse', 'HEAD', cwd=repo).decode().strip() == BASE
    assert not git('status', '--porcelain', '--', 'jobsearch_cn', 'tools', cwd=repo).strip()
    assert digest(FIX / 'oracle-manifest.json') == MANIFEST_HASH
    verify()
    input_commit = git('rev-parse', 'HEAD').decode().strip()
    for name in [*FROZEN_NAMES, 'oracle-manifest.json']:
        relative = (FIX / name).relative_to(ROOT).as_posix()
        assert git('show', f'{input_commit}:{relative}') == (FIX / name).read_bytes(), name
    out = FIX / 'actual' / 'master-d8ec9ad'
    data = ROOT / 'data' / 'v19-master-d8ec9ad'
    assert not out.exists() and not data.exists(), 'Never overwrite a recorded baseline.'
    out.mkdir(parents=True)
    (data / 'profile').mkdir(parents=True)
    shutil.copyfile(FIX / 'baseline-profile.json', data / 'profile' / 'profile.json')
    commands = []

    def safe(value):
        if isinstance(value, str):
            for path, label in ((data, '<data-dir>'), (repo, '<baseline-repo>'), (ROOT, '<workspace>')):
                value = value.replace(str(path), label).replace(path.as_posix(), label)
            return value
        if isinstance(value, list):
            return [safe(item) for item in value]
        if isinstance(value, dict):
            return {key: safe(item) for key, item in value.items()}
        return value

    def write(name, value):
        (out / name).write_text(json.dumps(safe(value), ensure_ascii=False, indent=2) + '\n',
                                encoding='utf-8', newline='\n')

    def cli(*args):
        args = [str(arg) for arg in args]
        command = [sys.executable, '-m', 'jobsearch_cn', *args, '--data-dir', str(data)]
        result = subprocess.run(command, cwd=repo, capture_output=True, encoding='utf-8',
                                env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONPATH': str(repo)})
        commands.append({'command': ['python', *command[1:]], 'exit_code': result.returncode,
                         'stderr': result.stderr})
        write('commands.json', commands)
        assert result.returncode == 0, (args[:2], result.returncode, 'see commands.json')
        assert not result.stderr.strip(), args[:2]
        return json.loads(result.stdout)

    validation = cli('profile', 'validate')
    write('profile-validation.json', validation)
    summary = {
        'code_commit': BASE, 'input_commit': input_commit, 'manifest_sha256': MANIFEST_HASH,
        'python_version': sys.version.split()[0], 'started_at_utc': datetime.now(timezone.utc).isoformat(),
        'scope': '旧schema投影与旧评分行为；未把新参数或新福利字段伪装成已支持',
        'new_contract_comparison': 'not_executed_before_m2_6e_pr', 'cases': [],
    }
    for case in read('expectations.json')['cases']:
        parsed = cli('jd', 'parse', FIX / case['fixture'], '--site', 'other', '--save')
        assert len(parsed['jobs']) == 1
        job = parsed['jobs'][0]
        write(case['id'] + '-parse.json', parsed)
        scored = cli('match', 'score', job['id'])
        write(case['id'] + '-score.json', scored)
        summary['cases'].append({
            'id': case['id'], 'parsed_salary': job['salary'],
            'salary_matches_manual_raw_amount': job['salary'] == case['salary'],
            'salary_dimension': scored['dimensions']['salary'],
            'future_score_status': case['score_status'], 'future_score': case['score'],
        })
    summary['raw_salary_equal'] = sum(case['salary_matches_manual_raw_amount'] for case in summary['cases'])
    summary['baseline_score_counts'] = dict(Counter(str(case['salary_dimension']['score']) for case in summary['cases']))
    summary['commands'] = len(commands)
    verify()
    assert digest(FIX / 'oracle-manifest.json') == MANIFEST_HASH
    write('summary.json', summary)
    hashes = {path.name: digest(path) for path in sorted(out.glob('*.json'))}
    write('output-manifest.json', {'sha256': hashes, 'input_manifest_sha256': MANIFEST_HASH})
    print(json.dumps({key: summary[key] for key in ('raw_salary_equal', 'baseline_score_counts', 'commands')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
