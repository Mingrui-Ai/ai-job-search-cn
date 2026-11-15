"""H25b: exercise the Windows venv redirector through the real PDF extraction CLI."""

import json
import os
import subprocess
import tempfile
import time
import unittest
import venv
from pathlib import Path

from tests.test_cn_resume_extract import REPO, make_pdf


@unittest.skipUnless(os.name == "nt", "Windows venv redirectors only")
class WindowsVenvPdf(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(directory.cleanup)
        cls.root = Path(directory.name)
        cls.environment = cls.root / "venv with spaces"
        venv.EnvBuilder(with_pip=False, symlinks=False).create(cls.environment)
        cls.python = cls.environment / "Scripts" / "python.exe"
        cls.backend = cls.environment / "Lib" / "site-packages" / "pypdf.py"
        cls.source = cls.root / "synthetic.pdf"
        make_pdf(cls.source)

    def run_python(self, *args):
        env = dict(os.environ, PYTHONPATH=str(REPO), PYTHONDONTWRITEBYTECODE="1",
                   PYTHONIOENCODING="utf-8")
        return subprocess.run([str(self.python), "-B", *args], cwd=self.root, env=env,
                              capture_output=True, timeout=30)

    def test_pdf_backend_installed_only_in_the_venv_is_still_available(self):
        # A local stand-in avoids installing an optional dependency during the test.
        self.backend.write_text(
            "class Page:\n"
            "    def extract_text(self):\n"
            "        return 'synthetic virtualenv-only PDF backend'\n"
            "class PdfReader:\n"
            "    def __init__(self, path):\n"
            "        self.pages = [Page()]\n", encoding="utf-8")
        before = self.source.read_bytes()
        result = self.run_python("-m", "jobsearch_cn", "profile", "extract", str(self.source))
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertEqual(result.stderr, b"")
        self.assertEqual(json.loads(result.stdout)["text"], "synthetic virtualenv-only PDF backend")
        self.assertEqual(self.source.read_bytes(), before)

    def test_pdf_timeout_ends_backend_descendants_in_a_venv(self):
        started = self.root / "backend-descendant-started.txt"
        marker = self.root / "backend-descendant-finished.txt"
        grandchild = ("import time; from pathlib import Path; "
                      f"Path({str(started)!r}).write_text('started'); time.sleep(3); "
                      f"Path({str(marker)!r}).write_text('finished')")
        self.backend.write_text(
            "import subprocess, sys, time\n"
            "class PdfReader:\n"
            "    def __init__(self, path):\n"
            f"        subprocess.Popen([sys.executable, '-c', {grandchild!r}])\n"
            "        time.sleep(5)\n"
            "        raise RuntimeError('synthetic private backend diagnostic')\n", encoding="utf-8")
        # Shorten the existing budget and delay assignment inside the CLI process. The
        # PDF bridge, optional-backend import, Job Object, and descendants all stay real.
        program = (
            "import runpy, sys, time\n"
            "from jobsearch_cn import resume_extract\n"
            "assign = resume_extract._windows_job\n"
            "def delayed_assignment(process):\n"
            "    time.sleep(1.5)\n"
            "    return assign(process)\n"
            "resume_extract._windows_job = delayed_assignment\n"
            "resume_extract._PDF_TIMEOUT = 0.8\n"
            f"sys.argv = ['jobsearch_cn', 'profile', 'extract', {str(self.source)!r}]\n"
            "runpy.run_module('jobsearch_cn', run_name='__main__')\n")
        result = self.run_python("-c", program)
        time.sleep(4)  # An escaped descendant would have written its marker by now.
        self.assertTrue(started.exists(), "the synthetic PDF backend's descendant never started")
        self.assertFalse(marker.exists(), "the PDF backend's descendant outlived the timeout")
        self.assertEqual(result.returncode, 2, result.stderr.decode("utf-8", "replace"))
        self.assertEqual(result.stdout, b"")
        self.assertIn("无法提取 PDF 文本", json.loads(result.stderr)["error"])
        self.assertNotIn(b"synthetic private backend diagnostic", result.stderr)


if __name__ == "__main__":
    unittest.main()
