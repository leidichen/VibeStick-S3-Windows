"""Compile the pure-C battery filter with the host compiler and run its self-test scenarios."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware" / "sticks3"


class FirmwareBatteryFilterTests(unittest.TestCase):
    def test_battery_filter_scenarios_pass(self) -> None:
        compiler = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
        if compiler is None:
            self.skipTest("no C compiler (cc/gcc/clang) on PATH")
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "host_battery_test"
            build = subprocess.run(
                [
                    compiler,
                    "-std=c11",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    f"-I{FIRMWARE / 'include'}",
                    "-o",
                    str(executable),
                    str(FIRMWARE / "tools" / "host_battery_test.c"),
                    str(FIRMWARE / "src" / "vibe_battery.c"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(executable)], capture_output=True, text=True, check=False)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("RESULT: PASS", run.stdout)


if __name__ == "__main__":
    unittest.main()
