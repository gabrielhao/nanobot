"""Run simple smoke checks for CogneeMemoryService without pytest.

This runner verifies:
 - add + cognify persistence across restarts
 - simple search and multi-hop behavior
 - error handling when cognify on missing node

Exit code 0 on success, 2 on failure.
"""
import sys
from pathlib import Path

# Import by path to avoid package import issues
import importlib.util
from pathlib import Path as _P
_cogpath = _P(__file__).resolve().parent.parent / 'nanobot' / 'services' / 'cognee_memory.py'
spec = importlib.util.spec_from_file_location('cognee_memory', str(_cogpath))
cog_mod = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = cog_mod
spec.loader.exec_module(cog_mod)
CogneeMemoryService = cog_mod.CogneeMemoryService
cognee = cog_mod.cognee
SearchType = cog_mod.SearchType


def fail(msg: str):
    print("FAIL:", msg)
    sys.exit(2)


def main():
    tmp = Path('.').resolve() / 'tmp_cognee_test'
    if tmp.exists():
        import shutil
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)

    # persistence test
    db_path = tmp / 'cognee_store.db'
    service = CogneeMemoryService(workspace=tmp, db_name=str(db_path.name))
    nid = service.add('Alice likes Python and testing.')
    meta = service.cognify(nid)
    if 'keywords' not in meta:
        fail('cognify did not produce keywords')
    service.close()

    # reopen
    svc2 = CogneeMemoryService(workspace=tmp, db_name=str(db_path.name))
    res = svc2.search('python testing', search_type=SearchType.GRAPH_COMPLETION)
    if not any('Alice' in r.content for r in res):
        fail('search did not return persisted content')
    svc2.close()

    # multi-hop
    s = CogneeMemoryService(workspace=tmp)
    a = s.add('Topic A root')
    b = s.add('Topic B child')
    c = s.add('Topic C child2')
    s.link(a, b)
    s.link(b, c)
    s.cognify(a); s.cognify(b); s.cognify(c)
    r = s.search('Topic', search_type=SearchType.GRAPH_COMPLETION)
    ids = [x.id for x in r]
    if a not in ids or b not in ids:
        fail('multi-hop search failed')

    # missing node
    try:
        s.cognify(99999999)
        fail('expected KeyError for missing node')
    except KeyError:
        pass

    print('All smoke checks passed')
    sys.exit(0)

if __name__ == '__main__':
    main()
