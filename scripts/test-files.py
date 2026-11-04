#!/usr/bin/env python3
"""Run public file tests with a private, isolated database path for each mode."""
# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parent.parent
goose = str(Path(sys.argv[1]).resolve())
with tempfile.TemporaryDirectory(prefix='goose-sqlite-public-') as tmp:
    path = Path(tmp)
    subprocess.run([goose, 'run', 'tests/files.goose', '--', str(path / 'runner.sqlite')], cwd=root, check=True)
    subprocess.run([goose, 'build', 'tests/files.goose', '-o', str(path / 'files')], cwd=root, check=True)
    subprocess.run([str(path / 'files'), str(path / 'native.sqlite')], cwd=root, check=True)
    subprocess.run([goose, 'run', 'tests/checkpoint.goose', '--', str(path / 'checkpoint-runner.sqlite')], cwd=root, check=True)
    subprocess.run([goose, 'build', 'tests/checkpoint.goose', '-o', str(path / 'checkpoint')], cwd=root, check=True)
    subprocess.run([str(path / 'checkpoint'), str(path / 'checkpoint-native.sqlite')], cwd=root, check=True)
