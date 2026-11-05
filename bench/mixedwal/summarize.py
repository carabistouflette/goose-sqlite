# SPDX-License-Identifier: Apache-2.0
"""Derive orientation-specific summaries and retain unchanged recorder artifacts."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import statistics
import tarfile

CALLERS = ['goose', 'raw-c-api', 'sqlitecpp', 'rusqlite', 'python']


def digest(data):
    return hashlib.sha256(data).hexdigest()


def spread(values):
    return dict(median=statistics.median(values), minimum=min(values), maximum=max(values))


def archive(source, output, name):
    paths = [source / f for f in ('metadata.json', 'samples.json', 'samples.jsonl', 'failure.json') if (source / f).is_file()]
    paths += [p for directory in ('pairs', 'source') for p in (source / directory).rglob('*')
              if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc']
    paths = sorted(paths)
    members = {}
    with (output / name).open('wb') as target:
        with gzip.GzipFile(fileobj=target, mode='wb', filename='', mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.USTAR_FORMAT) as tar:
                for p in paths:
                    if p.is_symlink():
                        raise ValueError('Unexpected artifact symlink')
                    raw = p.read_bytes()
                    relative = p.relative_to(source).as_posix()
                    info = tarfile.TarInfo(relative)
                    info.size, info.mode, info.mtime = len(raw), 0o644, 0
                    tar.addfile(info, io.BytesIO(raw))
                    members[relative] = dict(bytes=len(raw), sha256=digest(raw))
    return dict(sha256=digest((output / name).read_bytes()), bytes=(output / name).stat().st_size,
                member_count=len(members), members=members)


def summarize(source):
    data = json.loads((source / 'samples.json').read_bytes())
    assert data['complete'] and not data['development_smoke'] and not data['source_dirty']
    assert data['rounds'] == 10 and len(data['samples']) == data['pair_count'] == 50
    assert len(data['qualifications']) == 5
    rows = []
    wc, rc = data['topology']['writer_cpu'], data['topology']['reader_cpu']
    for writer_cpu, reader_cpu in [(wc, rc), (rc, wc)]:
        for caller in CALLERS:
            pairs = [s for s in data['samples'] if s['implementation'] == caller and s['writer_cpu'] == writer_cpu]
            assert len(pairs) == 5 and all(s['reader_cpu'] == reader_cpu for s in pairs)
            for role in ('reader', 'writer'):
                states = [s['result']['roles'][role] for s in pairs]
                assert all(s['result']['gates']['passed'] and s['result']['gates']['coverage_required'] for s in pairs)
                assert all(s['result']['child_exit_status'] == dict(reader=0, writer=0) for s in pairs)
                row = dict(implementation=caller, writer_cpu=writer_cpu, reader_cpu=reader_cpu, role=role, pair_count=5,
                           success_count=sum(s['successes'] for s in states), busy_count=sum(s['busy'] for s in states),
                           successes_per_pair=spread([s['successes'] for s in states]),
                           attempts_per_pair=spread([s['attempt_count'] for s in states]),
                           successful_operations_per_second=spread([s['successful_operations_per_second'] for s in states]),
                           role_window_ns=spread([s['window_ns'] for s in states]),
                           role_peak_rss_kib=spread([s['result']['role_peak_rss_kib'][role] for s in pairs]),
                           pair_wall_ns=spread([s['result']['pair_wall_ns'] for s in pairs]),
                           stop_dispatch_lag_ns=spread([s['result']['stop_dispatch_lag_ns'] for s in pairs]),
                           reader_done_lag_ns=spread([s['result']['reader_done_lag_ns'] for s in pairs]))
                for outcome in ('successful_latency', 'begin_busy_latency'):
                    ds = [s[outcome] for s in states]
                    row[outcome] = dict(count=sum(d['count'] for d in ds),
                        quantiles={q: spread([d['nearest_rank_ns'][q] for d in ds if d['count']]) if any(d['count'] for d in ds) else None for q in ('p50', 'p95', 'p99')},
                        minimum=min((d['minimum'] for d in ds if d['count']), default=None),
                        maximum=max((d['maximum'] for d in ds if d['count']), default=None))
                rows.append(row)
    return dict(source_commit=data['source_commit'], pair_count=50, qualification_count=5,
                attempts=data['attempts'], row_count=data['rows'], read_cap=data['read_cap'],
                reader_observations=sum(s['result']['roles']['reader']['attempt_count'] for s in data['samples']),
                writer_observations=sum(s['result']['roles']['writer']['attempt_count'] for s in data['samples']),
                parent_started_utc_ns=data['parent_started_utc_ns'], parent_completed_utc_ns=data['parent_completed_utc_ns'],
                measured_started_utc_ns=min(s['result']['pair_started_utc_ns'] for s in data['samples']),
                measured_completed_utc_ns=max(s['result']['pair_completed_utc_ns'] for s in data['samples']),
                statistics_scope='Medians and observed ranges of five per-pair summaries for each CPU orientation, never pooled quantiles or confidence intervals. Role RSS peaks are separate whole-lifetime peaks; never sum them.',
                workload_scope=data['scope'], rows=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--principal', type=Path, required=True)
    parser.add_argument('--qualification', type=Path, required=True)
    parser.add_argument('--ci-smoke', type=Path, required=True)
    parser.add_argument('--development-failure', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    summary = summarize(args.principal)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    archives = {}
    for source, name in [(args.principal, 'principal.tar.gz'), (args.qualification, 'qualification.tar.gz'), (args.ci_smoke, 'ci-smoke.tar.gz')]:
        archives[name] = archive(source, args.output, name)
    if args.development_failure is not None:
        archives['development-incomplete.tar.gz'] = archive(args.development_failure, args.output,
                                                            'development-incomplete.tar.gz')
    metadata = args.principal / 'metadata.json'
    (args.output / metadata.name).write_bytes(metadata.read_bytes())
    (args.output / 'manifest.json').write_text(json.dumps(dict(
        format='Deterministic gzip/ustar; original member bytes unchanged; timestamps/uid/gid normalized only in container headers.',
        retention='Sources, complete structured JSON/JSONL, qualification records, per-pair results, role stdout/stderr/RSS and event journals. Successful database/sidecars removed by recorder after verification; their hashes remain in results. Build binaries/caches excluded; identities retained in metadata.',
        archives=archives), indent=2) + '\n')
    print(json.dumps({k:v for k,v in summary.items() if k!='rows'}, indent=2))
    print({name:v['bytes'] for name,v in archives.items()})


if __name__ == '__main__':
    main()
