"""Compare frozen V10 inputs via public CLI in a separate, clean target checkout."""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from run_baseline import FIX, ROOT, MANIFEST_HASH, digest, get, norm, put, read, write


def git(*args, cwd=ROOT):
    return subprocess.check_output(['git', *args], cwd=cwd)


def verify_inputs():
    assert digest(FIX/'oracle-manifest.json') == MANIFEST_HASH
    manifest = read(FIX/'oracle-manifest.json')
    for name, expected in manifest['oracle_files_lf_sha256'].items():
        assert digest(FIX/name) == expected, name
    return manifest


def classify(field, expected, actual):
    if field in ('cities', 'requirements.skills'):
        wanted, found = {norm(s): s for s in expected}, {norm(s): s for s in actual}
        missing = [wanted[s] for s in sorted(wanted.keys()-found.keys())]
        extra = [found[s] for s in sorted(found.keys()-wanted.keys())]
        kind = 'wrong' if missing and extra else 'missing' if missing else 'extra' if extra else 'match'
        return {'type':kind,'expected':expected,'actual':actual,'missing':missing,'extra':extra}
    kind = ('match' if expected == actual else 'missing' if actual is None else
            'extra' if expected is None else 'wrong')
    return {'type':kind,'expected':expected,'actual':actual}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', required=True, help='Full immutable commit hash')
    parser.add_argument('--source', type=Path, required=True, help='Clean checkout outside the report repository')
    parser.add_argument('--label', required=True, help='New result directory; existing runs are never overwritten')
    args = parser.parse_args()
    assert re.fullmatch(r'[0-9a-f]{40}',args.target)
    assert re.fullmatch(r'[a-z0-9-]+',args.label)
    source = args.source.resolve()
    assert not source.is_relative_to(ROOT.resolve())
    assert git('rev-parse','HEAD',cwd=source).decode().strip() == args.target
    assert not git('status','--porcelain','--untracked-files=no',cwd=source).strip()
    manifest = verify_inputs()
    out, run = FIX/'actual'/args.label, ROOT/'data/v10-check'/args.label
    assert not out.exists() and not run.exists(), 'Use a fresh label'
    out.mkdir(parents=True)
    run.mkdir(parents=True)
    source_hashes = {p.relative_to(source).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                     for folder in ('jobsearch_cn','tools') for p in (source/folder).rglob('*')
                     if p.is_file() and '__pycache__' not in p.parts}
    profiles, adaptations = {}, {}
    for profile in ('tech','ops'):
        rel = f'tests/fixtures/cn/profile/{profile}/profile.json'
        frozen = git('show',manifest['base_commit']+':'+rel)
        assert hashlib.sha256(frozen.replace(b'\r\n',b'\n')).hexdigest() == manifest['source_files_lf_sha256'][rel]
        original = json.loads(frozen)
        target = json.loads(git('show',args.target+':'+rel))
        adapted = deepcopy(original)
        if 'acceptable_cities' not in adapted['availability']:
            adapted['availability']['acceptable_cities'] = []
            adaptations[profile] = 'Add availability.acceptable_cities=[] in temporary copy only; original fields unchanged'
        assert adapted == target, 'Any other profile change needs a separate explicit mapping'
        pp = run/'profiles'/profile/'profile.json'
        write(pp,adapted)
        profiles[profile] = pp
    commands = []
    def cli(*arguments, store=run/'parsed'):
        options = [] if arguments[:2] == ('jd','validate') else ['--data-dir',str(store)]
        argv = [sys.executable,'-m','jobsearch_cn',*map(str,arguments),*options]
        process = subprocess.run(argv,cwd=source,capture_output=True,encoding='utf-8',
                                 env={**os.environ,'PYTHONUTF8':'1','PYTHONPATH':str(source)})
        def safe(value):
            return value.replace(str(source),'<target-checkout>').replace(str(ROOT),'<workspace>')
        log = {'command':['python',*[safe(a) for a in argv[1:]]],
               'exit_code':process.returncode,'stderr':safe(process.stderr)}
        commands.append(log)
        write(out/'commands.json',commands)
        assert process.returncode == 0 and not process.stderr.strip(), log
        return json.loads(process.stdout)
    counts = Counter()
    baseline = read(FIX/'actual/master-c6055cc/summary.json')
    summary = {'target_commit':args.target,'baseline_commit':manifest['base_commit'],
               'manifest_lf_sha256':MANIFEST_HASH,'profile_adaptations':adaptations,
               'python_version':sys.version.split()[0],'started_at_utc':datetime.now(timezone.utc).isoformat(),
               'cases':{}}
    for path in sorted(FIX.glob('*.expected.json')):
        oracle = read(path)
        key = path.name.removesuffix('.expected.json')
        parsed = cli('jd','parse',FIX/oracle['fixture'],'--site',oracle['site_argument'],'--save')
        assert len(parsed['jobs']) == 1
        job = parsed['jobs'][0]
        fields = {field:classify(field,entry['value'],get(job,field)) for field,entry in oracle['fields'].items()}
        for comparison in fields.values():
            counts['fields_'+comparison['type']] += 1
        skill = fields['requirements.skills']
        counts['skill_expected'] += len(skill['expected'])
        counts['skill_hit'] += len(skill['expected'])-len(skill['missing'])
        counts['skill_missing'] += len(skill['missing'])
        counts['skill_extra'] += len(skill['extra'])
        evidence = {}
        for field, entry in oracle['fields'].items():
            value = get(job,field)
            if value is None or value == []:
                continue
            item = job['evidence'].get(field)
            quote = item.get('text') if item else None
            quotes = quote if isinstance(quote,list) else [quote]
            ok = bool(quotes) and all(isinstance(q,str) and q and q in job['raw_text'] for q in quotes)
            evidence[field] = {'evidence':item,'verbatim':ok}
            counts['evidence_values'] += 1
            counts['evidence_verbatim'] += ok
        manual = deepcopy(job)
        for field,entry in oracle['fields'].items():
            put(manual,field,entry['value'])
            if entry['value'] is None or entry['value'] == []:
                manual['evidence'].pop(field,None)
            else:
                manual['evidence'][field] = {'text':entry['evidence'],'method':'agent'}
        manual_path = run/'manual-input'/(key+'.json')
        write(manual_path,manual)
        validated = cli('jd','validate',manual_path)
        counts['manual_valid'] += validated['valid']
        saved = cli('jd','save',manual_path,store=run/'manual')
        counts['manual_saved'] += len(saved['saved']) == 1
        record = {'parse':parsed,'fields':fields,'evidence':evidence,'manual_job':manual,
                  'manual_validate':validated,'manual_save':saved,'profiles':{}}
        for profile,pp in profiles.items():
            filtered = cli('match','filter',job['id'],'--profile',pp)
            replay = cli('match','filter',job['id'],'--profile',pp,store=run/'manual')
            human = oracle['human_match'][profile]
            comparisons = {}
            for label, result in (('parsed',filtered),('manual',replay)):
                observed = {c['check']:c['result'] for c in result['checks']}
                assert human['checks'].keys() <= observed.keys()
                differences = {name:{'expected':entry['result'],'actual':observed[name]}
                               for name,entry in human['checks'].items() if entry['result'] != observed[name]}
                counts[label+'_old_checks_equal'] += len(human['checks'])-len(differences)
                counts[label+'_verdicts_equal'] += human['verdict'] == result['verdict']
                # New checks did not exist when V10 was frozen; observe separately.
                extra = {name:value for name,value in observed.items() if name not in human['checks']}
                comparisons[label] = {'expected_verdict':human['verdict'],'actual_verdict':result['verdict'],
                                      'old_check_differences':differences,'additional_checks':extra}
            record['profiles'][profile] = {'filter':filtered,'manual_filter':replay,'comparison':comparisons}
        old_job = read(FIX/'actual/master-c6055cc'/(key+'.json'))['parse']['jobs'][0]
        changed = {field:{'before':get(old_job,field),'after':get(job,field)}
                   for field in oracle['fields'] if get(old_job,field) != get(job,field)}
        summary['cases'][key] = {'field_groups_equal':sum(c['type']=='match' for c in fields.values()),
                                'differences':{f:c for f,c in fields.items() if c['type']!='match'},
                                'changes_from_baseline':changed,'education':job['requirements']['education'],
                                'skills':job['requirements']['skills'],
                                'additional_fields':{'interview':job.get('interview'),'start':job['requirements'].get('start')},
                                'profiles':{p:r['comparison'] for p,r in record['profiles'].items()}}
        write(out/(key+'.json'),record)
        print(key,summary['cases'][key]['field_groups_equal'],'/14',flush=True)
    verify_inputs()
    assert all(hashlib.sha256((source/p).read_bytes()).hexdigest()==h for p,h in source_hashes.items())
    assert git('rev-parse','HEAD',cwd=source).decode().strip() == args.target
    assert not git('status','--porcelain','--untracked-files=no',cwd=source).strip()
    summary.update({'counts':dict(counts),'baseline_metrics':{k:v for k,v in baseline.items()
                    if k in ('field_groups','skills','filter_verdicts','hard_checks','manual_replay_verdicts','manual_replay_checks')},
                    'successful_cli_calls':len(commands),'frozen_inputs_verified':len(manifest['oracle_files_lf_sha256']),
                    'target_source_unchanged':True,'finished_at_utc':datetime.now(timezone.utc).isoformat()})
    write(out/'summary.json',summary)
    print(json.dumps(summary['counts'],ensure_ascii=False))


if __name__ == '__main__':
    main()
