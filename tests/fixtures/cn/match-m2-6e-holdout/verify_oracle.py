"""Validate V19's manually written inputs, arithmetic and frozen hashes; no product imports."""
from collections import Counter
from fractions import Fraction
import hashlib
import json
from pathlib import Path

FIX = Path(__file__).resolve().parent
FROZEN_NAMES = [
    '.gitattributes', 'README.md', 'profile-parameters.json', 'baseline-profile.json',
    'expectations.json', 'verify_oracle.py',
    *sorted(path.name for path in FIX.glob('v19-*.txt')),
]


def read(name):
    return json.loads((FIX / name).read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify():
    for name in FROZEN_NAMES:
        data = (FIX / name).read_bytes()
        assert not data.startswith(b'\xef\xbb\xbf'), name
        assert b'\r' not in data, name
        data.decode('utf-8')
    params = read('profile-parameters.json')
    profile = read('baseline-profile.json')
    assert profile['target']['salary_min'] == {'amount': params['minimum_monthly'], 'unit': 'CNY/month'}
    assert profile['availability']['days_per_week'] == params['working_days_per_week']
    cases = read('expectations.json')['cases']
    assert len(cases) == 9
    assert len({case['id'] for case in cases}) == len(cases)
    assert {case['fixture'] for case in cases} == {p.name for p in FIX.glob('v19-*.txt')}
    evidence_count = 0

    def salary_score(amount):
        if amount < params['minimum_monthly']:
            return Fraction(0)
        if amount <= params['ideal_monthly']:
            return Fraction(50)
        return min(Fraction(100), 50 + (amount - params['ideal_monthly']) *
                   Fraction(params['points_per_step'], params['step_monthly']))

    for case in cases:
        text = (FIX / case['fixture']).read_text(encoding='utf-8')
        for snippet in [case['salary_evidence'], *case['benefit_evidence']]:
            assert snippet in text, (case['id'], 'evidence not in source')
            evidence_count += 1
        salary = case['salary']
        middle = None if salary['min'] is None else Fraction(salary['min'] + salary['max'], 2)
        assert middle == case['salary_midpoint'], case['id']
        if middle is None or salary['unit'] == 'CNY/hour':
            monthly = None
        elif salary['unit'] == 'CNY/day':
            monthly = middle * params['working_days_per_week'] * Fraction(52, 12)
        elif salary['unit'] == 'CNY/year':
            monthly = middle / 12
        else:
            assert salary['unit'] == 'CNY/month'
            monthly = middle
        assert monthly == case['base_monthly'], case['id']
        meal = case['meal_credit_monthly']
        if meal is not None:
            assert meal == (params['provided_meals_monthly_equivalent'] if case['meals_per_day'] in (2, 3) else 0)
        subsidy = case['cash_subsidy']
        assert case['cash_subsidy_monthly'] == (subsidy['amount'] if subsidy['status'] == 'stated_amount' else 0)
        if monthly is not None and meal is not None:
            comparable = monthly + meal + case['cash_subsidy_monthly']
            assert comparable == case['comparable_monthly'], case['id']
            assert salary_score(comparable) == case['exact_capped_score'], case['id']
        else:
            assert case['comparable_monthly'] is None and case['exact_capped_score'] is None
        if case['score_status'] == 'fixed':
            assert case['score'] == case['exact_capped_score']
        else:
            assert case['score'] is None
        for option in case.get('conditional_outcomes', []):
            assert monthly + option['meal_credit_monthly'] == option['comparable_monthly']
            assert salary_score(Fraction(option['comparable_monthly'])) == option['exact_capped_score']
    manifest = FIX / 'oracle-manifest.json'
    if manifest.exists():
        hashes = read(manifest.name)['frozen_files_sha256']
        assert set(hashes) == set(FROZEN_NAMES)
        for name, expected in hashes.items():
            assert digest(FIX / name) == expected, (name, 'frozen input changed')
    return {'cases': len(cases), 'nontechnical': sum(case['direction'] != 'tech' for case in cases),
            'evidence_snippets': evidence_count,
            'score_status': dict(Counter(case['score_status'] for case in cases)),
            'frozen_files': len(FROZEN_NAMES)}


if __name__ == '__main__':
    print(json.dumps(verify(), ensure_ascii=False))
