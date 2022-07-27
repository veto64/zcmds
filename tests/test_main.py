import os
import sys
import unittest
from subprocess import check_output

from zcmds.install.update import main as install_zcmds
from zcmds.paths import (
    BIN_DIR,
    CMD_COMMON_DIR,
    CMD_DARWIN_DIR,
    CMD_DIR,
    CMD_LINUX_DIR,
    CMD_WIN32_DIR,
    PROJECT_ROOT,
)

ALL_DIRS = [
    PROJECT_ROOT,
    BIN_DIR,
    CMD_DIR,
    CMD_COMMON_DIR,
    CMD_WIN32_DIR,
    CMD_DARWIN_DIR,
    CMD_LINUX_DIR,
]

install_zcmds()

def exec(cmd: str) -> str:
    stdout = check_output(cmd, shell=True, universal_newlines=True)
    return stdout


class MainTester(unittest.TestCase):
    def test_imports(self) -> None:
        from static_ffmpeg.run import check_system

        check_system()

    def test_zmcds(self) -> None:
        stdout = exec("zcmds")
        # self.assertIn("shrink", stdout)
        self.assertIn("vidclip", stdout)

    @unittest.skipIf(sys.platform == "win32", "win32 test only")
    def test_ls(self) -> None:
        # Tests that ls works on windows.
        _ = exec("ls")
        _ = exec("which")



if __name__ == "__main__":
    unittest.main()
