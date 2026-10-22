# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Opt-in one-snapshot supervisor and read-only bundle/evidence verification.

Import, --verify-bundle and --inspect never construct a device adapter.
The internal Windows worker is selected only with explicit live authorization.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import time
import pnp_coverage_v2 as original
import pnp_rejection_v1 as companion

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'pnp-snapshot-build-v1'
EXECUTION_SECONDS = 5
CLEANUP_SECONDS = 2
MAX_FILES = 8192
MAX_BUNDLE = 8*1024*1024
POLICIES = dict(original='pnp-coverage-v2', companion='pnp-rejection-v1',
                scope='one-initial-snapshot-no-notifications', recovery_accepted=False,
                observer_collection_complete=False, query_ms=250, query_calls=32768,
                execution_seconds=EXECUTION_SECONDS, cleanup_seconds=CLEANUP_SECONDS,
                retries=0)
PERMIT = b'pnp-snapshot-v1\nAUTHORIZE EXACTLY ONE INITIAL SNAPSHOT\n'
SCENARIOS = {'good','missing-hid','historical-root','own-target','own-other','own-unknown',
             'partial','full-partial','malformed','empty','unsupported','exact-counts',
             'detail-cap','writer-fault','cleanup-fault','query-timeout'}


def need(value, reason):
    if not value:
        raise ValueError(reason)


def digest(path):
    total = 0
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''):
            total += len(chunk)
            need(total <= 1024*1024*1024, 'file_byte_limit')
            h.update(chunk)
    return h.hexdigest()


def load_json(path, cap=MAX_BUNDLE):
    with Path(path).open('rb') as f:
        raw = f.read(cap+1)
    need(0 < len(raw) <= cap, 'json_byte_limit')
    def constant(_): raise ValueError('nonfinite_json')
    try:return json.loads(raw, object_pairs_hook=companion._pairs, parse_constant=constant)
    except RecursionError:raise ValueError('json_depth_limit') from None


def local_path(name, root=ROOT):
    need(type(name) is str and len(name) <= 1024 and '\\' not in name and ':' not in name,
         'invalid_bundle_path')
    path = PurePosixPath(name)
    need(not path.is_absolute() and path.parts and all(p not in ('..','.') for p in path.parts)
         and str(path) == name, 'invalid_bundle_path')
    value = root.joinpath(*path.parts)
    need(value.resolve() == value.absolute() and value.is_relative_to(root), 'redirected_bundle_path')
    return value


def verify_bundle(path, expected_sha, *, allow_host_test=False, root=ROOT):
    """Read-only and bounded; caller retains the externally reviewed bundle hash."""
    need(type(expected_sha) is str and re.fullmatch('[0-9a-f]{64}',expected_sha), 'invalid_bundle_hash')
    need(Path(path).stat().st_size <= MAX_BUNDLE,'bundle_byte_limit')
    need(digest(path) == expected_sha, 'bundle_hash_mismatch')
    b = load_json(path)
    need(type(b) is dict and set(b) == {'schema','origin','source_commit','baseline','files',
         'sources','executables','toolchain','protected_inputs','policies'}, 'bundle_schema')
    need(b['schema'] == SCHEMA and b['baseline'] == 'c449a26c288750eaf40c49a41a3a4ef1e635b752', 'bundle_version')
    need(b['origin'] == 'offline-build' or (allow_host_test and b['origin']=='HOST TEST'), 'bundle_origin')
    need(type(b['source_commit']) is str and re.fullmatch('[0-9a-f]{40}', b['source_commit']), 'source_commit')
    need(b['policies'] == POLICIES and all(type(b['policies'][k]) is type(v) for k,v in POLICIES.items()), 'policy_changed')
    files = b['files']
    need(type(files) is dict and 0 < len(files) <= MAX_FILES, 'file_count_limit')
    total = 0
    for name, item in files.items():
        p = local_path(name, root)
        need(type(item) is dict and set(item) in ({'sha256','bytes'},{'sha256','bytes','mtime_ns'}), 'input_schema')
        need(type(item['bytes']) is int and 0 <= item['bytes'] <= 1024*1024*1024 and
             type(item['sha256']) is str and re.fullmatch('[0-9a-f]{64}',item['sha256']), 'input_bounds')
        total += item['bytes']; need(total <= 4*1024*1024*1024, 'total_input_byte_limit')
        stat = p.stat()
        need(stat.st_size == item['bytes'] and digest(p) == item['sha256'], 'input_hash_mismatch')
        if 'mtime_ns' in item:
            need(type(item['mtime_ns']) is str and str(stat.st_mtime_ns)==item['mtime_ns'], 'preservation_mtime_mismatch')
    for key in ('sources','protected_inputs'):
        names = b[key]
        need(type(names) is list and len(names)<=MAX_FILES and all(type(n) is str for n in names) and
             len(names)==len(set(names)) and all(n in files for n in names), 'input_reference')
    need(type(b['executables']) is dict and set(b['executables'])=={'host','windows','original_pnp'}, 'executable_roles')
    need(all((type(v) is str and v in files) or (b['origin']=='HOST TEST' and v is None) for v in b['executables'].values()), 'executable_reference')
    need(b['executables']['host'] in files, 'missing_host_worker')
    if b['origin']=='offline-build':
        need(len(b['protected_inputs'])==975 and type(b['toolchain']) is str and b['toolchain'] in files and
             len(b['sources'])>=39 and all(b['executables'].values()), 'incomplete_production_bundle')
        t = load_json(local_path(b['toolchain'],root),1024*1024)
        need(type(t) is dict and all(k in t for k in ('windows_sdk_version','compiler','generator','inputs')) and
             t['windows_sdk_version'] and t['compiler'] and t['generator'] and
             type(t['inputs']) is list and t['inputs'] and all(n in files for n in t['inputs']), 'toolchain_metadata')
        need(t.get('python_sha256') == digest(Path(__import__('sys').executable)), 'python_identity_changed')
        need(t.get('source_commit') == b['source_commit'] and type(t.get('binary_sha256')) is dict and
             all(t['binary_sha256'].get(role)==files[b['executables'][role]]['sha256'] for role in ('host','windows')),
             'compiled_identity_metadata')
    return b


def inspect_streams(folder, *, host_test=False):
    try:
        pn = original.load(Path(folder)/'pnp-v2.jsonl')
        pv = original.validate(pn,allow_host_test=host_test,require_complete=False)
    except (OSError,ValueError,TypeError):raise ValueError('original_stream_invalid') from None
    try:
        dg = companion.read(Path(folder)/'rejection-v1.jsonl')
        dv = companion.validate(dg,pn,allow_host_test=host_test)
    except (OSError,ValueError,TypeError,StopIteration):raise ValueError('companion_stream_invalid') from None
    snapshots = [r for r in pn if r['event']=='snapshot']
    need(len(snapshots)==1 and snapshots[0]['sample']==1 and
         sum(r['event']=='snapshot_begin' for r in pn)==1, 'not_exactly_one_snapshot')
    need(not any(r['event'] in ('registration','unregistration','receipt','classification','drain') for r in pn), 'unexpected_notification_lifecycle')
    need(not pv['collection_complete'] and pn[-1]['collection_complete'] is False, 'false_observer_completeness')
    s = snapshots[0]
    # Frozen Collector::Ready, independently checked without relaxing any own-ID,
    # global-coverage, startup or active-interface requirement.
    nodes = [r for r in pn if r['event']=='devnode']
    qualified = any(r['role']=='hid_child' and r['hardware']=='target_hid' and
        r['present']==r['root_present']==r['started']==1 and r['status_code']==r['problem']==0 and
        not r['status'] & 0x400 and r['root_status_code']==r['root_problem']==0 and r['root_started']==1 and
        r['ancestry_complete'] and r['ancestry_code']==0 for r in nodes)
    ready = bool(s['coverage_complete'] and not s['incomplete_identity_coverage'] and
        s['roots']==s['present_qualified_roots']==1 and s['multiple_present_candidates']==0 and
        s['unresolved_roots']==s['indeterminate']==s['interface_indeterminate']==0 and
        s['active_usb']>=1 and s['active_hid']>=1 and not s['ambiguous'] and qualified)
    need(s['initial_ready'] is ready, 'snapshot_readiness_mismatch')
    failures = [dict(domain=domain,reason=r['reason'],qpc=r['qpc'])
                for domain,rows in (('original',pn),('companion',dg))
                for r in rows if r['event']=='first_failure']
    failures.sort(key=lambda r:r['qpc'])
    return dict(schema='pnp-snapshot-inspection-v1',origin=pn[0]['origin'],snapshot_ready=ready,
        original=pv,companion=dv,first_failure=failures[0] if failures else None,
        original_first_failure=next((r['reason'] for r in pn if r['event']=='first_failure'),None),
        companion_first_failure=next((r['reason'] for r in dg if r['event']=='first_failure'),None),
        original_cleanup_ok=next(r['code']==0 for r in pn if r['event']=='cleanup'),
        expected_worker_exit=1 if pv['first_failure'] is not None or not ready else (0 if dg[-1]['writer_ok'] and not dg[-1]['diagnostic_failure'] else 3),
        observer_collection_complete=False,recovery_accepted=False)


class Journal:
    def __init__(self,path):
        self.file = Path(path).open('xb',buffering=0)
        self.rows = self.bytes = 0
        self.failed = False

    def append(self,event,**fields):
        if self.failed: return False
        try:
            raw = (json.dumps(dict(schema='pnp-snapshot-session-v1',sequence=self.rows,
                monotonic=time.perf_counter(),event=event,**fields),allow_nan=False,separators=(',',':'))+'\n').encode()
            need(self.rows < 128 and self.bytes+len(raw) <= 65536,'journal_capacity')
            need(self.file.write(raw)==len(raw),'journal_write')
            self.rows+=1; self.bytes+=len(raw)
            return True
        except (OSError,ValueError):
            self.failed=True
            return False

    def close(self): self.file.close()


def native_failure_candidate(folder):
    """Retain a flushed native first-failure even if its later stream is partial.

    This is explicitly unvalidated until the independent complete readers pass.
    It never grants readiness or stream completeness.
    """
    found=[]
    for domain,name,cap,schema in (
        ('original','pnp-v2.jsonl',8*1024*1024,'pnp-coverage-v2'),
        ('companion','rejection-v1.jsonl',1048576,'pnp-rejection-v1')):
        try:
            with (Path(folder)/name).open('rb') as f:raw=f.read(cap+1)
            if len(raw)>cap:continue
            for line in raw.split(b'\n')[:-1]:
                if len(line)>16384:break
                r=json.loads(line,object_pairs_hook=companion._pairs)
                if r.get('event')=='first_failure' and set(r)=={'schema','sequence','qpc','event','reason'} and r['schema']==schema:
                    valid=(type(r['reason']) is int and 1<=r['reason']<=9) if domain=='original' else r['reason'] in companion.FAILURES
                    if valid and type(r['qpc']) is int and r['qpc']>0:
                        found.append(dict(domain=domain,reason=r['reason'],qpc=r['qpc'],evidence_validated=False))
                    break
        except (OSError,ValueError,TypeError):pass
    return min(found,key=lambda r:r['qpc']) if found else None


def supervise(command,folder,api,job,*,host_test=True,clock=time.perf_counter,pause=time.sleep):
    """Owned one-root lifecycle; fake APIs exercise all branches on Linux too.

    The caller pins inputs before this function. No guard/audio process exists.
    Every actual Windows process is atomically assigned before its first thread.
    """
    folder=Path(folder);journal=Journal(folder/'session-v1.jsonl')
    first=None;process=None;released=False;inspection=None
    forced=False;unknown=False;normal=False;close_ok=False;empty_after=False;child_seen=False
    exit_code=None;cleanup_errors=[];evidence_errors=[];last=None;log_files=[]
    def fail(domain,reason,**metadata):
        nonlocal first
        if first is None:
            first=dict(domain=domain,reason=reason,**metadata)
            journal.append('first_failure',failure=first)
    def members():
        nonlocal last,unknown
        value=job.members()
        state=(value.active,value.pids,value.exact,value.code)
        if state!=last:
            journal.append('job_members',active=value.active,pids=value.pids,exact=value.exact,code=value.code)
            last=state
        unknown |= not value.exact
        return value
    def poll():
        nonlocal released,exit_code
        if process is not None and not released and process.poll() is not None:
            exit_code=process.returncode
            journal.append('root_exit',exit_code=exit_code)
            job.release(process);released=True
    journal.append('header',origin='HOST TEST' if host_test else 'authorized-initial-snapshot',
                   execution_seconds=EXECUTION_SECONDS,cleanup_seconds=CLEANUP_SECONDS,retries=0)
    try:
        for name in ('stdout.txt','stderr.txt'):
            log_files.append((folder/name).open('xb'))
        process=api.spawn(command,job,*log_files)
        journal.append('spawn_owned',pid=process.pid)
        deadline=clock()+EXECUTION_SECONDS
        while True:
            poll()
            candidate=native_failure_candidate(folder)
            if candidate:fail(**candidate)
            value=members()
            if not value.exact:
                fail('process','job_membership_unknown');break
            child_seen |= any(pid!=process.pid for pid in value.pids)
            if released and value.empty:
                normal=True;break
            if clock()>=deadline:
                fail('process','unexpected_child_lifetime' if child_seen else 'execution_deadline');break
            pause(.01)
        if normal:
            try:
                inspection=inspect_streams(folder,host_test=host_test)
                f=inspection['first_failure']
                if f: fail(f['domain'],f['reason'])
                if first and first.get('domain') in ('original','companion'):
                    first['evidence_validated']=True
                expected=inspection['expected_worker_exit']
                if exit_code!=expected:fail('process','unexpected_exit_code')
                if not inspection['original_cleanup_ok']:fail('original','cleanup_failed')
                if not inspection['companion']['diagnostic_complete']:fail('companion','diagnostic_incomplete')
            except (OSError,ValueError,StopIteration) as error:
                evidence_errors.append(str(error) if str(error) in ('original_stream_invalid','companion_stream_invalid') else 'invalid_snapshot_contract')
                candidate=native_failure_candidate(folder)
                if candidate:fail(**candidate)
                fail('evidence',evidence_errors[-1])
    except (OSError,ValueError):
        fail('process','owned_lifecycle_error')
    finally:
        # A broken native stream cannot hide its already flushed first failure.
        candidate=native_failure_candidate(folder)
        if candidate:fail(**candidate)
        if journal.failed:fail('evidence','journal_write_failed')
        journal.append('cleanup_begin',first_failure=first)
        end=clock()+CLEANUP_SECONDS
        if not normal:
            forced=True;journal.append('forced_containment')
            try:api.contain(job)
            except OSError:cleanup_errors.append('containment_failed')
        try:
            while True:
                poll();value=members()
                if (process is None or released) and value.empty:
                    empty_after=True;break
                if clock()>=end:break
                pause(.01)
        except OSError:cleanup_errors.append('membership_or_release_failed');unknown=True
        try:job.close();close_ok=True
        except OSError:cleanup_errors.append('job_close_failed')
        for f in log_files:f.close()
        certified=normal and empty_after and close_ok and released and not forced and not unknown and not cleanup_errors
        if not certified:fail('cleanup','cleanup_not_certified')
        cleanup=dict(root_exit_code=exit_code,root_handle_released=released,
            job_empty_before_close=empty_after,normal_tree_exit=normal,
            forced_containment=forced,membership_unknown_seen=unknown,close_ok=close_ok,
            child_members_observed=child_seen,job_close_may_force=not empty_after,errors=cleanup_errors,fully_certified=certified)
        journal.append('cleanup',**cleanup)
        result=dict(schema='pnp-snapshot-result-v1',origin='HOST TEST' if host_test else 'authorized-initial-snapshot',
            first_failure=first,inspection=inspection,cleanup=cleanup,evidence_errors=evidence_errors,
            journal_ok=not journal.failed,recovery_accepted=False,automatic_retries=0)
        journal.append('summary',first_failure=first,recovery_accepted=False)
        if journal.failed:fail('evidence','journal_write_failed')
        result['first_failure']=first
        result['journal_ok']=not journal.failed
        journal.close()
        with (folder/'result-v1.json').open('x',encoding='utf-8') as f:json.dump(result,f,indent=2,allow_nan=False)
    return result


def run(bundle_path,bundle_sha,output,*,authorize=False,host_scenario=None):
    host=host_scenario is not None
    need((host and host_scenario in SCENARIOS and not authorize) or (authorize is True and not host), 'explicit_authorization_required')
    need(os.name=='nt','owned_windows_supervisor_required')
    b=verify_bundle(bundle_path,bundle_sha,allow_host_test=host)
    if not host:need(b['origin']=='offline-build','host_bundle_cannot_query')
    from coordinator_windows_v1 import ProcessAPI,WindowsJob
    api=ProcessAPI();pins=[];job=None
    output=Path(output).absolute()
    need(output.resolve()==output,'redirected_output')
    try:
        for path in [Path(bundle_path).resolve(),Path(__import__('sys').executable).resolve(),*[local_path(n) for n in b['files']]]:
            pins.append(api.pin_read(path))
        verify_bundle(bundle_path,bundle_sha,allow_host_test=host)
        output.mkdir(exist_ok=False)
        if host:
            command=[str(local_path(b['executables']['host'])),'--host-test',host_scenario,str(output)]
        else:
            with (output/'query-permit-v1.txt').open('xb') as f:f.write(PERMIT)
            command=[str(local_path(b['executables']['windows'])),'--authorized-one-initial-snapshot-v1',str(output)]
        job=WindowsJob()
        result=supervise(command,output,api,job,host_test=host)
        job=None
        verify_bundle(bundle_path,bundle_sha,allow_host_test=host)
        return result
    finally:
        if job is not None and job.handle:job.close()
        for h in reversed(pins):h.Close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--verify-bundle',action='store_true')
    modes.add_argument('--inspect',type=Path)
    modes.add_argument('--host-test',choices=sorted(SCENARIOS))
    modes.add_argument('--run-initial-snapshot',action='store_true')
    parser.add_argument('--bundle',type=Path);parser.add_argument('--bundle-sha256')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--authorize-one-initial-snapshot',action='store_true')
    parser.add_argument('--allow-host-test',action='store_true')
    args=parser.parse_args()
    try:
        if args.inspect:
            need(not args.authorize_one_initial_snapshot,'unexpected_authorization')
            result=inspect_streams(args.inspect,host_test=args.allow_host_test)
        elif args.verify_bundle:
            need(not args.authorize_one_initial_snapshot and args.bundle and args.bundle_sha256,'bundle_arguments')
            b=verify_bundle(args.bundle,args.bundle_sha256,allow_host_test=args.allow_host_test)
            result=dict(schema=SCHEMA,source_commit=b['source_commit'],files=len(b['files']),verified=True)
        else:
            need(args.bundle and args.bundle_sha256 and args.output,'run_arguments')
            need(not args.allow_host_test,'unexpected_host_override')
            result=run(args.bundle,args.bundle_sha256,args.output,
                authorize=args.authorize_one_initial_snapshot,host_scenario=args.host_test)
        print(json.dumps(result,allow_nan=False))
        return 1 if result.get('first_failure') or result.get('journal_ok') is False else 0
    except (OSError,ValueError,TypeError):
        print('Snapshot harness rejected; preserve all evidence. No retry.')
        return 1

if __name__=='__main__':raise SystemExit(main())
