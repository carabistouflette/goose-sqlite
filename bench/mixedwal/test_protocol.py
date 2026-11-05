#!/usr/bin/env python3
"""Exercise bounded command backpressure with real owned child processes."""
# SPDX-License-Identifier: Apache-2.0
import importlib.util
import os
from pathlib import Path
import signal
import sys
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('mixedwal_subject', Path(__file__).with_name('measure.py'))
SUBJECT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SUBJECT)


class CommandBackpressure(unittest.TestCase):
    def test_full_pipe_fails_and_all_owned_resources_close(self):
        cpu = min(os.sched_getaffinity(0))
        runner = [sys.executable, '-c', 'import signal; signal.pause()']
        with tempfile.TemporaryDirectory(prefix='sqlite-command-backpressure-') as temporary:
            directory = Path(temporary)
            pair = SUBJECT.Pair({'stalled': runner}, 'stalled', directory / 'unused.db',
                                'mixed', 8, 4, 10, cpu, cpu, directory, os.environ.copy())

            def deadline(*_):
                raise TimeoutError('Command backpressure exceeded finite probe deadline')

            previous = signal.signal(signal.SIGALRM, deadline)
            signal.setitimer(signal.ITIMER_REAL, 2)
            try:
                # The actor intentionally never reads stdin. Fill the actual pipe,
                # then exercise the normal buffered write/flush and failure cleanup.
                descriptor = pair.children['reader'].stdin.fileno()
                for _ in range(1024):
                    try:
                        os.write(descriptor, b'N\n' * 1024)
                    except BlockingIOError:
                        break
                else:
                    self.fail('Stalled actor pipe did not fill within the probe bound')
                with self.assertRaises(BlockingIOError):
                    pair.send('reader', 'N')
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
                signal.signal(signal.SIGALRM, previous)
                pair.abort()
                pair.close(suppress_errors=True)
            for child in pair.children.values():
                self.assertIsNotNone(child.poll())
                self.assertTrue(all(pipe.closed for pipe in (child.stdin, child.stdout, child.stderr)))
            self.assertTrue(pair.events.closed)
            self.assertTrue(all(stream.closed for stream in pair.streams))
            self.assertFalse(pair.selector.get_map())


if __name__ == '__main__':
    unittest.main()
