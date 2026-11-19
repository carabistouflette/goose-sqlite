# SPDX-License-Identifier: Apache-2.0
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('sanitize_driver',Path(__file__).resolve().parents[1]/'scripts/sanitize.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)


class CacheIdentity(unittest.TestCase):
    def test_wrapper_and_compiler_content_changes_freeze_new_paths(self):
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw);(root/'scripts').mkdir()
            script=root/'scripts/sanitizer-cc.sh';script.write_text('first flags')
            cc=root/'gcc';cc.write_text('first compiler')
            goose=root/'goose';goose.write_text('pinned compiler')
            with patch.object(runner,'ROOT',root):
                first=runner.compiler_wrapper(cc,goose)
                self.assertEqual(first,runner.compiler_wrapper(cc,goose))
                script.write_text('changed flags')
                second=runner.compiler_wrapper(cc,goose)
                self.assertNotEqual(first,second)
                self.assertEqual(first.read_text(),'first flags')
                cc.write_text('changed compiler')
                self.assertNotEqual(second,runner.compiler_wrapper(cc,goose))

    def test_link_only_symbols_do_not_pass_object_gate(self):
        with patch.object(runner.CONTROL.subprocess,'check_output',return_value=' U memcpy\n U __asan_init\n'):
            with self.assertRaisesRegex(RuntimeError,'compile-time'):runner.CONTROL.require_instrumentation(Path('/fake/object'))


if __name__=='__main__':unittest.main()
