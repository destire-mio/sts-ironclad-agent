"""Real pipe closure must not prevent the next training stage from running."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('training_resume',
    Path(__file__).resolve().parents[1] / 'agent/heart_training_resume.py')
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)


class DurableTrainingLogTest(unittest.TestCase):
    def test_closed_reader_aborts_old_path_but_detached_controller_finishes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worker = root / 'worker.py'
            worker.write_text("""from pathlib import Path
import sys
import time
root = Path(sys.argv[1])
print('collection complete', flush=True)
while not (root / 'proceed').exists():
    time.sleep(.01)
print('starting training', flush=True)
print('diagnostic stderr', file=sys.stderr, flush=True)
(root / 'training-finished').write_text('complete')
""")
            old, fixed = root / 'old', root / 'fixed'
            old.mkdir(); fixed.mkdir()
            process = subprocess.Popen([sys.executable, '-u', str(worker), str(old)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(process.stdout.readline().strip(), 'collection complete')
                process.stdout.close()
                (old / 'proceed').touch()
                self.assertNotEqual(process.wait(timeout=5), 0)
                self.assertIn('BrokenPipeError', process.stderr.read())
                self.assertFalse((old / 'training-finished').exists())
            finally:
                if process.poll() is None:
                    process.kill(); process.wait()
                process.stderr.close()

            # The launching process itself has a closed consumer and exits.
            # Its controller must retain both log streams and finish the stage.
            launcher = root / 'launcher.py'
            launcher.write_text(f"""import importlib.util
spec = importlib.util.spec_from_file_location('resume', {str(Path(R.__file__).resolve())!r})
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
module.detached({[sys.executable, '-u', str(worker), str(fixed)]!r},
                {str(fixed / 'controller.log')!r}, {str(fixed)!r})
""")
            launcher_process = subprocess.Popen([sys.executable, str(launcher)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            launcher_process.stdout.close()
            self.assertEqual(launcher_process.wait(timeout=5), 0)
            launcher_process.stderr.close()
            (fixed / 'proceed').touch()
            import time
            deadline = time.monotonic() + 5
            while not (fixed / 'training-finished').exists() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual((fixed / 'training-finished').read_text(), 'complete')
            self.assertIn('starting training', (fixed / 'controller.log').read_text())
            self.assertIn('diagnostic stderr', (fixed / 'controller.log').read_text())

    def test_process_failure_remains_failure_and_log_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'controller.log'
            child = R.detached([sys.executable, '-c',
                "import sys; print('specific failure', file=sys.stderr); sys.exit(7)"], path, directory)
            self.assertEqual(child.wait(timeout=5), 7)
            content = path.read_bytes()
            with self.assertRaises(FileExistsError):
                R.detached([sys.executable, '-c', 'pass'], path, directory)
            self.assertEqual(path.read_bytes(), content)

    def test_existing_attempt_rejected_before_any_import_or_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'execution').mkdir()
            with self.assertRaisesRegex(AssertionError, 'preserve the recovery attempt'):
                R.check(root)
            self.assertEqual(list(root.iterdir()), [root / 'execution'])


if __name__ == '__main__':
    unittest.main()
