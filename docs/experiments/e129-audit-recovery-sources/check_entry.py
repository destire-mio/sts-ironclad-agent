"""Exercise audit reuse rejection and actual incomplete-source admission."""
import copy
import sys
import recover_audit as A


def main():
    chunk = {'seed': 0, 'identity': {'engine_sha256': 'engine', 'model_sha256': 'model'},
             'sources': [{'seed': 12, 'split': 'fit', 'path': '/fixture', 'sha256': 'source'}]}
    good = {'status': 'audited', 'identity': chunk['identity'], 'sources': chunk['sources'],
            'cases': [{'seed': 12, 'split': 'fit'}]}
    assert A.validate_audit(good, chunk)
    bad = []
    value = copy.deepcopy(good); value['identity']['engine_sha256'] = 'changed'; bad.append(('engine', value))
    value = copy.deepcopy(good); value['identity']['model_sha256'] = 'changed'; bad.append(('model', value))
    value = copy.deepcopy(good); value['sources'][0]['sha256'] = 'changed'; bad.append(('source', value))
    value = copy.deepcopy(good); value['cases'] = []; bad.append(('missing_case', value))
    value = copy.deepcopy(good); value['cases'][0]['split'] = 'label_holdout'; bad.append(('role', value))
    bad.append(('audit_error', {'status': 'audit_error', 'error': 'fixture replay differs'}))
    timeout = {'seed': 0, 'status': 'timeout', 'target': None, 'exitcode': -9}
    bad.append(('timeout_cannot_admit', timeout))
    rejected = []
    for name, value in bad:
        try:
            A.validate_audit(value, chunk)
        except AssertionError:
            rejected.append(name)
        else:
            raise AssertionError('invalid cached audit accepted: ' + name)
    assert A.validate_audit(timeout, chunk, allow_interrupted=True) is False
    sys.path.insert(0, str(A.COLLECTOR))
    import run_collections as C
    assert not (A.SOURCE / 'completion-verification.json').exists()
    try:
        C.source_ready(A.COLLECTOR)
    except FileNotFoundError as error:
        assert str(A.SOURCE / 'completion-verification.json') in str(error)
    else:
        raise AssertionError('incomplete source admitted')
    assert all(not (A.COLLECTOR / name).exists() for name in ('relic-source', 'joint', 'execution-started.json'))
    assert all(not (A.TRAINING / name).exists() for name in ('execution', 'scale', 'training-execution.json'))
    result = {'status': 'passed', 'valid_cached_audit_accepted': True,
        'deadline_timeout_resumable_but_not_admitted': True, 'rejected': rejected,
        'actual_incomplete_source_rejected_before_collection_or_training': True,
        'recovery_sha256': A.sha(A.ROOT / 'recover_audit.py'), 'checker_sha256': A.sha(__file__)}
    A.write(A.ROOT / 'entry-verification.json', result)
    print(result)


if __name__ == '__main__':
    main()
