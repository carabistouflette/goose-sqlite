#!/usr/bin/env python3
"""Interleave two native Goose binaries using the retained baseline fixtures."""
# SPDX-License-Identifier: Apache-2.0
import argparse
import json
import os
from pathlib import Path
import platform
import random
import time
from measure import ROOT, digest, engine, measured, output


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--before', required=True, type=Path)
    ap.add_argument('--after', required=True, type=Path)
    ap.add_argument('--baseline-results', required=True, type=Path)
    ap.add_argument('--after-build', required=True, type=Path)
    ap.add_argument('--output', required=True, type=Path)
    ap.add_argument('--runs', type=int, default=7)
    ap.add_argument('--cpu', type=int)
    args = ap.parse_args()
    if not 1 <= args.runs <= 100: ap.error('Invalid run count')
    if args.cpu is not None: os.sched_setaffinity(0, {args.cpu})
    base = json.loads(args.baseline_results.read_text())
    after_build = json.loads(args.after_build.read_text())
    bins = {'before': args.before.resolve(), 'after': args.after.resolve()}
    hashes = {name: digest(path) for name,path in bins.items()}
    if hashes['before'] != base['binaries']['goose']: raise RuntimeError('Baseline binary mismatch')
    for key in ('compiler','build_type','flags'):
        if after_build[key] != base['native_build'][key]: raise RuntimeError('Different compiler/profile')
    library = engine(bins['before'])
    if library != engine(bins['after']) or library != base['sqlite_libraries']['goose']:
        raise RuntimeError('Different SQLite engine')
    source_commit = output(['git','rev-parse','HEAD'])
    sources = {p: digest(ROOT / p) for p in base['source_hashes']}
    changed = {p for p in sources if sources[p] != base['source_hashes'][p]}
    if changed != {'native/sqlite.c','sqlite.build'}:
        raise RuntimeError(f'Unexpected measured source changes: {changed}')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    journal = args.output.with_suffix('.jsonl'); journal.write_text('')
    samples = []; rng = random.Random(219)
    started = time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
    fixtures = list(dict.fromkeys((s['fixture'],s['bytes']) for s in base['samples']))
    for mode,size in fixtures:
        refs = {(s['iterations'],s['operations'],s['checksum']) for s in base['samples'] if s['fixture']==mode and s['bytes']==size}
        if len(refs)!=1: raise RuntimeError('Inconsistent baseline fixture')
        n,operations,checksum = refs.pop()
        for path in bins.values(): output([path,'1' if mode=='scan' else '10',mode,str(size)])
        for repeat in range(args.runs):
            order = list(bins); rng.shuffle(order)
            for position,name in enumerate(order):
                utc_start = time.time_ns(); start = time.perf_counter_ns()
                raw,rss = measured([bins[name],str(n),mode,str(size)],args.output.parent)
                wall = time.perf_counter_ns()-start; utc_end = time.time_ns()
                elapsed,actual = map(int,raw.split())
                if elapsed<=0 or actual!=checksum: raise RuntimeError('Invalid paired result')
                sample = dict(revision=name,fixture=mode,bytes=size,iterations=n,operations=operations,
                              run=repeat,order=position,loop_wall_ns=elapsed,checksum=actual,
                              peak_rss_kib=rss,whole_wall_ns=wall,whole_start_utc_ns=utc_start,whole_end_utc_ns=utc_end)
                samples.append(sample)
                with journal.open('a') as stream: stream.write(json.dumps(sample)+'\n')
    if source_commit != output(['git','rev-parse','HEAD']) or any(digest(ROOT / p)!=h for p,h in sources.items()):
        raise RuntimeError('Measured source changed')
    if any(digest(path)!=hashes[name] or engine(path)!=library for name,path in bins.items()):
        raise RuntimeError('Measured binary/engine changed')
    record = dict(started_utc=started,completed_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
                  before_source_commit=base['source_commit'],after_source_commit=source_commit,
                  after_source_dirty=bool(output(['git','status','--porcelain'])),after_source_hashes=sources,
                  before_binary_sha256=hashes['before'],after_binary_sha256=hashes['after'],
                  before_native_build=base['native_build'],after_native_build=after_build,
                  sqlite_library=library,goose_revision=base['goose_revision'],goose_sha256=base['goose_sha256'],
                  baseline_results_sha256=digest(args.baseline_results),harness_sha256=digest(Path(__file__)),
                  os=platform.platform(),affinity=sorted(os.sched_getaffinity(0)),order_seed=219,
                  scope='Matched native executables, shuffled before/after per fixture. Same compiler/profile, runner and SQLite engine; only native registry lookup and native fingerprint differ. Shared host; no dynamic-runner timing or isolated-core claim.',samples=samples)
    args.output.write_text(json.dumps(record,indent=2)+'\n')
    print(f'{len(samples)} paired checked samples: {args.output}')


if __name__ == '__main__':
    main()
