#!/usr/bin/env python3
"""Validate this specification bundle, never claim application/ML tests ran."""
from __future__ import annotations
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import pydantic
from pydantic import ValidationError
from contracts.models import (
    SCHEMA_MODELS, ApiPayloads, AnswerEnvelope, ChatRequest, Document,
    SpecialistResult, VehicleSafetyArgs, WorkshopArgs,
)


def read(path):
    return json.loads((ROOT / path).read_text())


def expected_exports():
    result = {}
    for name, model in SCHEMA_MODELS.items():
        schema = model.model_json_schema()
        result[name] = {"$schema": "https://json-schema.org/draft/2020-12/schema", **schema}
    result['tool-schemas.json'] = [
        {"type": "function", "function": {
            "name": "vehicle_safety_lookup",
            "description": "Search recall campaigns and optionally complaints via NHTSA MCP. Vehicle is taken from validated backend context, not tool arguments.",
            "parameters": VehicleSafetyArgs.model_json_schema(),
        }},
        {"type": "function", "function": {
            "name": "workshop_consult",
            "description": "Retrieve allowed applicable technical context and call the small assembly specialist for a checklist, plan review or post-repair checks.",
            "parameters": WorkshopArgs.model_json_schema(),
        }},
    ]
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--export', action='store_true')
    args = parser.parse_args()
    exports = expected_exports()
    if args.export:
        for name, value in exports.items():
            (ROOT/'contracts'/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
        print('Exported 3 payload schemas and 2 application tool schemas.')
        return

    results = []
    def check(name, fn):
        try:
            details = fn()
            results.append(dict(name=name, status='pass', details=details))
        except Exception as exc:
            results.append(dict(name=name, status='fail', error=str(exc)))

    def json_files():
        files = [p for p in ROOT.rglob('*.json') if p.name not in {'VALIDATION_REPORT.json', 'FILE_MANIFEST.json'}]
        for p in files:
            json.loads(p.read_text())
        return dict(files=len(files))
    check('all_json_parses', json_files)

    def dag_and_traceability():
        tasks = read('backlog/tasks.json')['tasks']
        cases = read('backlog/acceptance.json')['cases']
        reqs = read('backlog/requirements.json')['requirements']
        task_map = {x['id']:x for x in tasks}
        ac_ids = {x['id'] for x in cases}
        req_ids = {x['id'] for x in reqs}
        assert len(task_map)==len(tasks) and len(ac_ids)==len(cases) and len(req_ids)==len(reqs), 'duplicate IDs'
        assert all(x['status']=='todo' for x in tasks), 'implementation must remain todo in planning bundle'
        assert all(x['status']=='not_run' for x in cases), 'application acceptance not executed'
        for t in tasks:
            assert set(t['depends_on']) <= task_map.keys(), f"unknown dependency {t['id']}"
            assert set(t['requirements']) <= req_ids, f"unknown requirement {t['id']}"
            assert set(t['acceptance_ids']) <= ac_ids, f"unknown acceptance {t['id']}"
            assert t['done_when'] and t['deliverables_planned'], f"unreviewable task {t['id']}"
        seen=set(); active=set(); ordered=[]
        def visit(i):
            assert i not in active, f'cycle at {i}'
            if i in seen: return
            active.add(i)
            for d in task_map[i]['depends_on']: visit(d)
            active.remove(i);seen.add(i);ordered.append(i)
        for i in task_map:visit(i)
        for r in reqs:
            actual={t['id'] for t in tasks if r['id'] in t['requirements']}
            assert actual and actual==set(r['tasks']), f"requirements mapping drift {r['id']}"
            assert set(r['acceptance_ids']) <= ac_ids and r['acceptance_ids'], f"requirement without acceptance {r['id']}"
        covered={a for t in tasks for a in t['acceptance_ids']}
        assert covered==ac_ids, 'acceptance not assigned to a task'
        return dict(tasks=len(tasks), acceptance_cases=len(cases), requirements=len(reqs), topological_order=ordered)
    check('task_dag_and_requirement_links', dag_and_traceability)

    def early_workshop():
        milestones=read('backlog/milestones.json')['milestones']
        w=next(x for x in milestones if x['id']=='W01')
        assert w['depends_on']==['T13'], 'workshop must not wait for final release documentation'
        assert w['date'] is None and w['status']=='pending', 'unknown course dates must not be invented'
        return 'W01 can run after technical MVP, independently of T23/T24'
    check('early_workshop_milestone',early_workshop)

    def schemas_current():
        for name, value in exports.items():
            assert read('contracts/'+name)==value, f'{name}: re-export after contract change'
        return 'Pydantic JSON Schema exports match canonical model definitions; this is not an independent standards validator.'
    check('schema_exports_match', schemas_current)

    positives = {
        'examples/chat-request.json':ChatRequest,
        'examples/specialist-result.json':SpecialistResult,
        'examples/document.json':Document,
        'examples/answer.json':AnswerEnvelope,
        'examples/api-payloads.json':ApiPayloads,
    }
    for path, model in positives.items():
        def positive(path=path,model=model):
            model.model_validate(read(path))
            return model.__name__
        check('valid_fixture:'+path, positive)

    negatives = {
        'examples/invalid-history.json':ChatRequest,
        'examples/invalid-specialist.json':SpecialistResult,
        'examples/invalid-citation.json':AnswerEnvelope,
        'examples/invalid-model-provenance.json':AnswerEnvelope,
    }
    for path, model in negatives.items():
        def negative(path=path,model=model):
            try:model.model_validate(read(path))
            except ValidationError:return 'rejected as expected'
            raise AssertionError('invalid fixture accepted')
        check('invalid_fixture_rejected:'+path,negative)

    def unseen_specialist_source():
        answer=copy.deepcopy(read('examples/answer.json'))
        extra=copy.deepcopy(answer['evidence'][0])
        extra['evidence_id']='E_OTHER_SOURCE'
        answer['evidence'].append(extra)
        answer['specialist']['result']['checks'][0]['evidence_ids']=['E_OTHER_SOURCE']
        try:AnswerEnvelope.model_validate(answer)
        except ValidationError:return 'an evidence ID in the final envelope is insufficient if not supplied to specialist'
        raise AssertionError('specialist may cite unseen source')
    check('specialist_cannot_cite_other_envelope_source', unseen_specialist_source)

    def document_hash():
        d=read('examples/document.json')
        assert hashlib.sha256(d['content'].encode()).hexdigest()==d['content_sha256']
        return 'fictional document content hash matches'
    check('fixture_document_hash',document_hash)

    def local_links():
        checked=0
        for p in ROOT.rglob('*.md'):
            text=p.read_text()
            for target in re.findall(r'\]\(([^\s)]+)(?:\s+"[^"]*")?\)', text):
                if target.startswith(('http://','https://','mailto:','#','sandbox:')):continue
                rel=target.split('#',1)[0]
                if not rel:continue
                dest=(p.parent/rel).resolve()
                generated_report = ROOT/'VALIDATION_REPORT.json'
                assert dest.is_file() or dest==generated_report, f'{p.relative_to(ROOT)} -> missing {target}'
                checked+=1
        return dict(links=checked)
    check('local_markdown_links',local_links)

    report=dict(
        scope='Specification bundle only: no live MCP, application, hosting or training tests executed.',
        validated_at=datetime.now(timezone.utc).isoformat(),
        python=sys.version.split()[0],pydantic=pydantic.__version__,
        status='pass' if all(x['status']=='pass' for x in results) else 'fail',
        checks=results,
    )
    (ROOT/'VALIDATION_REPORT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(status=report['status'],checks=len(results),failures=[x for x in results if x['status']=='fail']),ensure_ascii=False,indent=2))
    if report['status']!='pass':raise SystemExit(1)


if __name__=='__main__':
    main()
