import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "hypr-displays")


class CliTest(unittest.TestCase):
    def test_version_runs_without_gtk_or_hyprland(self):
        out = subprocess.run([sys.executable, SCRIPT, "--version"], capture_output=True, text=True, check=True)
        self.assertRegex(out.stdout, r"^hypr-displays \d+\.\d+\.\d+$")

    def test_finds_core_module_through_a_symlink(self):
        # install.sh --link puts a symlink in ~/.local/bin; the core module must still be found.
        tmp = os.path.join(ROOT, "tests", "_link_test")
        os.makedirs(tmp, exist_ok=True)
        link = os.path.join(tmp, "hypr-displays")
        try:
            os.symlink(SCRIPT, link)
            subprocess.run([sys.executable, link, "--version"], capture_output=True, check=True)
        finally:
            if os.path.lexists(link):
                os.remove(link)
            os.rmdir(tmp)


if __name__ == "__main__":
    unittest.main()
