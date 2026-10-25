import sys
import unittest
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "src")
)

import sourcecourt


class PackageSmokeTest(unittest.TestCase):
    def test_package_import(self):
        self.assertEqual(sourcecourt.__version__, "1.1.2")


if __name__ == "__main__":
    unittest.main()
