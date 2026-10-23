# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""File-only closed-schema HOST TEST stage-ledger reader. Never acquires devices."""
import argparse
import collections
import json
from pathlib import Path
import pnp_coverage_v2 as original
from pnp_rejection_v1 import read, need, integer, boolean

BASE=set('schema origin sequence qpc event'.split())
FIELDS={
    'header':set('frequency diagnostic_ms scan_ms row_cap byte_cap detail_cap token_cap parent_cap source_call_cap'.split()),
    'scope_start':set('begin deadline clock_valid'.split()),
    'stage_begin':set('id parent stage optional remaining_ticks'.split()),
    'stage_end':set('id begin end elapsed_ticks remaining_ticks clock_valid'.split()),
    'anchors':set('targets system_root discovery_complete present_complete'.split()),
    'detail':set('attempt source reason relation chain collected_qpc'.split()),
    'first_failure':set('domain reason failure_qpc'.split()),
    'scope_end':set('begin end elapsed_ticks remaining_ticks clock_valid'.split()),
    'summary':set('total node interfaces retained omitted target other unknown reasons original_reason original_qpc '
                  'diagnostic_reason diagnostic_qpc original_ready cleanup_ok detail_complete attribution_complete '
                  'diagnostic_complete recovery_accepted'.split()),
}
STAGES=set('present_enumeration system_root_lookup qualified_root_discovery raw_property_acquisition '
           'acquisition_cache_population rejection_classification bounded_ancestry detail_serialization '
           'interface_enumeration scope_completion cleanup final_publication'.split())
FAILURES={'diagnostic_time_limit','clock_error','writer_failure','resource_limit','cleanup_failure'}

def validate(rows,native=None):
    need(type(rows) is list and 4<=len(rows)<=4096,'ledger row count')
    need(type(rows[0]) is dict and type(rows[-1]) is dict and rows[0].get('event')=='header' and rows[-1].get('event')=='summary','missing ledger header/footer')
    stack=[]; stages=[]; begun={}; ended=set();details=[];failures={};anchor=None;start=None;scope_end=None
    last=0;last_detail=0;clock_valid=True
    for sequence,row in enumerate(rows):
        need(type(row) is dict,'ledger object required')
        event=row.get('event');need(type(event) is str and event in FIELDS and set(row)==BASE|FIELDS[event],'closed ledger schema')
        need(row['schema']=='diagnostic-stage-ledger-v1' and row['origin']=='HOST TEST','host origin required')
        need(type(row['sequence']) is int and row['sequence']==sequence,'ledger sequence')
        integer(row['qpc']);need(row['qpc']>=last,'ledger nonmonotonic publication');last=row['qpc']
        if event=='header':
            need(sequence==0,'duplicate header')
            expected=dict(frequency=10000000,diagnostic_ms=25,scan_ms=250,detail_cap=64,token_cap=128,parent_cap=8,source_call_cap=32768)
            for key,value in expected.items():need(type(row[key]) is int and row[key]==value,'policy changed')
            integer(row['row_cap'],16,4096);integer(row['byte_cap'],4096,1048576)
            need(len(rows)<=row['row_cap'],'declared row cap')
        elif event=='scope_start':
            need(start is None,'duplicate scope');start=row;boolean(row['clock_valid']);integer(row['begin'])
            integer(row['deadline'],-1);need(row['begin']==row['qpc'],'scope start bracket')
            if row['clock_valid']:need(row['deadline']==row['begin']+250000,'shared total deadline')
            else:need(row['deadline']==-1,'unknown deadline');clock_valid=False
        elif event=='stage_begin':
            need(start is not None and scope_end is None,'stage outside scope')
            integer(row['id'],1);integer(row['parent']);boolean(row['optional'])
            need(row['id']==len(begun)+1 and type(row['stage']) is str and row['stage'] in STAGES,'stage ID/category')
            need(row['parent']==(stack[-1]['id'] if stack else 0),'stage nesting')
            integer(row['remaining_ticks'],-1,250000)
            if row['remaining_ticks']>=0:need(row['remaining_ticks']==max(start['deadline']-row['qpc'],0),'remaining budget')
            if row['optional']:
                need(not failures.get('diagnostic') and row['remaining_ticks']>0 and row['qpc']<start['deadline'],'optional work after expiry/failure')
            stack.append(row);begun[row['id']]=row;need(len(stack)<=32,'stage nesting cap')
        elif event=='stage_end':
            integer(row['id'],1)
            need(stack and row['id']==stack[-1]['id'],'unbalanced stage')
            entry=stack.pop();need(row['id'] not in ended,'duplicate end');ended.add(row['id'])
            integer(row['begin']);integer(row['end']);boolean(row['clock_valid'])
            need(row['begin']==entry['qpc'] and row['end']==row['qpc'] and row['end']>=row['begin'],'stage bracket')
            integer(row['elapsed_ticks'],-1);integer(row['remaining_ticks'],-1,250000)
            if row['clock_valid']:
                need(row['elapsed_ticks']==row['end']-row['begin'] and row['remaining_ticks']==max(start['deadline']-row['end'],0),'stage duration/budget')
            else:
                need(row['elapsed_ticks']==row['remaining_ticks']==-1,'clock uncertainty must be explicit');clock_valid=False
            stages.append(dict(stage=entry['stage'],optional=entry['optional'],parent=entry['parent'],**{k:row[k] for k in ('id','begin','end','elapsed_ticks','remaining_ticks','clock_valid')}))
        elif event=='first_failure':
            need(type(row['domain']) is str and row['domain'] in {'original','diagnostic'} and row['domain'] not in failures,'first failure overwritten')
            integer(row['failure_qpc']);need(row['failure_qpc']<=row['qpc'],'failure observation ordering')
            if row['domain']=='original':integer(row['reason'],1,9)
            else:
                need(type(row['reason']) is str and row['reason'] in FAILURES,'bounded diagnostic failure')
                if row['reason']=='diagnostic_time_limit':need(start and row['failure_qpc']>=start['deadline'],'premature time failure')
            failures[row['domain']]=row
        elif event=='anchors':
            need(start is not None and anchor is None,'anchor lifecycle');anchor=row
            boolean(row['discovery_complete']);boolean(row['present_complete']);integer(row['system_root'],0,128)
            need(type(row['targets']) is list and len(row['targets'])<=128,'anchor cap')
            for token in row['targets']:integer(token,1,128)
            need(len(set(row['targets']))==len(row['targets']),'duplicate anchor')
            need(row['system_root'] not in row['targets'],'system root is not qualified USB parent')
        elif event=='detail':
            need(anchor is not None and scope_end is None,'detail lifecycle');integer(row['attempt'],1,6144)
            need(row['attempt']>last_detail and len(details)<64,'detail order/cap');last_detail=row['attempt']
            need(type(row['source']) is str and row['source'] in {'present_devnode','usb_interface','hid_interface'},'detail source')
            need(type(row['reason']) is str and row['reason'] in original.REASONS-{'none'} and type(row['relation']) is str and row['relation'] in {'target','other','unknown'},'bounded detail category')
            integer(row['collected_qpc']);need(start['begin']<=row['collected_qpc']<start['deadline'] and row['collected_qpc']<=row['qpc'],'late/unproved collection')
            chain=row['chain'];need(type(chain) is list and 1<=len(chain)<=9,'chain bounds')
            for token in chain:integer(token,1,128)
            need(len(set(chain))==len(chain),'chain cycle')
            if row['relation']=='target':need(chain[-1] in anchor['targets'],'missing target anchor proof')
            if row['relation']=='other':need(anchor['discovery_complete'] and anchor['present_complete'] and anchor['targets'] and anchor['system_root'] and chain[-1]==anchor['system_root'],'missing independent outside-branch proof')
            details.append(row)
        elif event=='scope_end':
            need(start is not None and scope_end is None and not stack,'scope end lifecycle');scope_end=row
            boolean(row['clock_valid']);integer(row['begin']);integer(row['end']);integer(row['elapsed_ticks'],-1);integer(row['remaining_ticks'],-1,250000)
            need(row['begin']==start['begin'] and row['end']==row['qpc'],'scope bracket')
            if row['clock_valid']:need(row['elapsed_ticks']==row['end']-row['begin'] and row['remaining_ticks']==max(start['deadline']-row['end'],0),'scope duration/budget')
            else:need(row['elapsed_ticks']==row['remaining_ticks']==-1,'unknown final duration');clock_valid=False
        elif event=='summary':
            need(sequence==len(rows)-1 and scope_end is not None,'summary lifecycle')
    summary=rows[-1]
    need(not stack and len(ended)==len(begun),'incomplete stages')
    for key in ('total','node','interfaces','retained','omitted','target','other','unknown'):integer(summary[key],0,6144)
    for key in ('original_ready','cleanup_ok','detail_complete','attribution_complete','diagnostic_complete','recovery_accepted'):boolean(summary[key])
    need(summary['recovery_accepted'] is False,'ledger never grants recovery')
    need(summary['total']==summary['node']+summary['interfaces']==summary['retained']+summary['omitted']==summary['target']+summary['other']+summary['unknown'],'aggregate conservation')
    need(summary['retained']==len(details),'detail count')
    relation=collections.Counter(d['relation'] for d in details)
    need((summary['target'],summary['other'],summary['unknown'])==(relation['target'],relation['other'],relation['unknown']+summary['omitted']),'unknown omissions conservation')
    need(type(summary['reasons']) is list and len(summary['reasons'])<=len(original.REASONS),'reason cap')
    reasons={}
    for item in summary['reasons']:
        need(type(item) is dict and set(item)=={'reason','count'} and type(item['reason']) is str and item['reason'] in original.REASONS-{'none'} and item['reason'] not in reasons,'reason histogram schema')
        integer(item['count'],1,6144);reasons[item['reason']]=item['count']
    need(sum(reasons.values())==summary['total'],'reason conservation')
    retained_reasons=collections.Counter(d['reason'] for d in details)
    need(all(reasons.get(k,0)>=v for k,v in retained_reasons.items()),'retained reason exceeds aggregate')
    for domain,code_key,tick_key in [('original','original_reason','original_qpc'),('diagnostic','diagnostic_reason','diagnostic_qpc')]:
        integer(summary[tick_key]);integer(summary[code_key],0,9) if domain=='original' else need(type(summary[code_key]) is str and summary[code_key] in FAILURES|{'none'},'reason vocabulary')
        failure=failures.get(domain)
        need((summary[code_key],summary[tick_key])==((failure['reason'],failure['failure_qpc']) if failure else ((0,0) if domain=='original' else ('none',0))),'failure summary replaced')
    if clock_valid and scope_end['end']>=start['deadline']:need('diagnostic' in failures,'final-tail failure hidden')
    if not clock_valid:need('diagnostic' in failures,'clock failure hidden')
    complete=not failures.get('diagnostic') and clock_valid and summary['omitted']==0
    need(summary['detail_complete']==complete and summary['attribution_complete']==(summary['unknown']==0),'completeness mismatch')
    need(summary['diagnostic_complete']==(complete and summary['cleanup_ok'] and summary['unknown']==0),'false diagnostic completeness')
    bound=False
    if native is not None:
        original.validate(native,allow_host_test=True,require_complete=False)
        snapshots=[r for r in native if r['event']=='snapshot'];need(len(snapshots)==1,'exactly one original snapshot')
        snap=snapshots[0];need(anchor is not None,'missing anchors')
        need(snap['indeterminate']==summary['node'] and snap['interface_indeterminate']==summary['interfaces'] and {r['reason']:r['count'] for r in snap['classification_failures']}==reasons,'original aggregates changed')
        need(snap['initial_ready']==summary['original_ready'],'original readiness changed')
        failure=next((r for r in native if r['event']=='first_failure'),None)
        need((summary['original_reason'],summary['original_qpc'])==((failure['reason'],failure['qpc']) if failure else (0,0)),'original first failure changed')
        cleanup=next(r for r in native if r['event']=='cleanup');need(summary['cleanup_ok']==(cleanup['code']==0),'original cleanup changed')
        need(len(anchor['targets'])<=snap['present_qualified_roots'],'unsupported target anchors')
        bound=True
    firsts=[(r['failure_qpc'],domain) for domain,r in failures.items()];firsts.sort()
    first_domain='none' if not firsts else 'tie' if len(firsts)>1 and firsts[0][0]==firsts[1][0] else firsts[0][1]
    return dict(schema='stage-ledger-inspection-v1',origin='HOST TEST',bound_to_original=bound,
                diagnostic_complete=summary['diagnostic_complete'] if bound else False,summary=summary,stages=stages,
                scope=scope_end,first_domain=first_domain,recovery_accepted=False)

def inspect(folder):
    folder=Path(folder);rows=read(folder/'ledger-v1.jsonl')
    return validate(rows,original.load(folder/'pnp-v2.jsonl'))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path);args=p.parse_args()
    print(json.dumps(inspect(args.folder),indent=2))

if __name__=='__main__':main()
