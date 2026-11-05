#!/usr/bin/env python3
"""Profile frozen checked workloads; Callgrind counts are not native timings."""
# SPDX-License-Identifier: Apache-2.0
import argparse
import json
import os
import platform
import shutil
from pathlib import Path
import re

from paired import build, digest, engine, revision, run, snapshot, sqlite_identity, verify_snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--goose', required=True, type=Path)
    parser.add_argument('--ref', default='HEAD')
    parser.add_argument('--cpu', type=int)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    goose = args.goose.resolve(strict=True)
    output = args.output.resolve()
    if args.cpu is not None and args.cpu not in os.sched_getaffinity(0):
        parser.error('CPU must belong to the allowed affinity set')
    commit = revision(args.ref)
    output.mkdir(parents=True, exist_ok=False)
    source, cache, binary = output / 'snapshot', output / 'cache', output / 'runner'
    tool_files = [Path(__file__), Path(__file__).with_name("paired.py"), Path(__file__).with_name("measure.py")]
    tool_hashes = {p.name: digest(p) for p in tool_files}
    metadata = dict(source_commit=commit, profiler_sources=tool_hashes, os=platform.platform(),
                    cpu_model=next((v.split(":", 1)[1].strip() for v in Path("/proc/cpuinfo").read_text().splitlines() if v.startswith("model name")), ""), complete=False,
                    scope='Whole-process Callgrind Ir including setup and every-byte verification. Instrumented clock output is not native timing. Shared host; no isolation or speedup claim.',
                    affinity=[args.cpu] if args.cpu is not None else sorted(os.sched_getaffinity(0)),
                    profiles=[])
    def save():
        (output / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    save()
    try:
        env = os.environ.copy()
        for key in ('CFLAGS', 'CXXFLAGS', 'CPPFLAGS', 'LDFLAGS'):
            env.pop(key, None)
        metadata['source'] = snapshot(commit, source)
        version = run([goose, '--version'])[0].strip()
        declared = (source / 'GOOSE_REVISION').read_text().strip()
        reported = re.match(r'goose ([0-9a-f]{7,40})(?:\s|$)', version)
        if reported is None or not declared.startswith(reported[1]):
            raise RuntimeError('Goose does not match the source compiler pin')
        metadata['native_build'], _ = build(source, cache, binary, goose, env)
        metadata['engine'] = engine(binary)
        links = run(['ldd', binary])[0]
        library = Path(next(line.split('=>', 1)[1].split('(', 1)[0].strip()
                            for line in links.splitlines() if 'libsqlite3' in line and '=>' in line))
        metadata['sqlite_identity'] = sqlite_identity(library)
        metadata['tools'] = {name: dict(file=Path(shutil.which(name)).name,
                                      sha256=digest(Path(shutil.which(name))))
                             for name in ('valgrind', 'callgrind_annotate', 'objdump')}
        metadata['goose'] = dict(revision=(source / 'GOOSE_REVISION').read_text().strip(),
                                 sha256=digest(goose), version=version)
        metadata['valgrind_version'] = run(['valgrind', '--version'])[0].strip()
        prefix = ['taskset', '-c', str(args.cpu)] if args.cpu is not None else []
        for name, count, mode, size in (('scan128B', 100, 'scan', 128),
                                         ('lookup128B', 10000, 'lookup', 128),
                                         ('text4096B', 10000, 'text', 4096)):
            profile = output / (name + '.callgrind')
            stdout, stderr = run([*prefix, 'valgrind', '--tool=callgrind',
                                  '--callgrind-out-file=' + str(profile), binary,
                                  str(count), mode, str(size)], timeout=300)
            (output / (name + '.stdout')).write_text(stdout)
            (output / (name + '.stderr')).write_text(stderr)
            fields = stdout.split()
            expected = count * size * (1024 if mode == 'scan' else 1)
            if len(fields) != 2 or int(fields[1]) != expected:
                raise RuntimeError('Profile checksum mismatch')
            (output / (name + '.stdout')).write_text(stdout)
            (output / (name + '.stderr')).write_text(stderr)
            for label, inclusive in (('self', 'no'), ('inclusive', 'yes')):
                annotation = run(['callgrind_annotate', '--inclusive=' + inclusive,
                                  '--threshold=98', profile])[0]
                (output / (name + '-' + label + '.txt')).write_text(annotation)
            summary = re.search(r'^summary: (\d+)$', profile.read_text(), re.MULTILINE)
            if not summary:
                raise RuntimeError('Missing instruction summary')
            metadata['profiles'].append(dict(name=name, iterations=count, mode=mode,
                                              bytes=size, checksum=expected, raw_stdout=stdout.strip(),
                                              total_Ir=int(summary[1]), profile_sha256=digest(profile)))
            save()
        (output / 'fetch-disassembly.txt').write_text(
            run(['objdump', '-d', '--disassemble=gq_fetch', binary])[0])
        verify_snapshot(source, metadata['source'])
        if {p.name: digest(p) for p in tool_files} != tool_hashes:
            raise RuntimeError('Profiler sources changed during execution')
        if digest(binary) != metadata['native_build']['binary_sha256'] or engine(binary) != metadata['engine'] or digest(goose) != metadata['goose']['sha256']:
            raise RuntimeError('Binary, engine or compiler changed during execution')
        metadata['complete'] = True
    except Exception as error:
        metadata['failure'] = str(error)
        raise
    finally:
        save()


if __name__ == '__main__':
    main()
