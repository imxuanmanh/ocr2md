"""Mark Windows wheels platform-specific when they carry the Windows extractor."""
import sys

from setuptools import setup
from wheel.bdist_wheel import bdist_wheel


class BundledWheel(bdist_wheel):
    def finalize_options(self):
        super().finalize_options()
        if sys.platform == "win32":
            self.root_is_pure = False

    def get_tag(self):
        python, abi, platform = super().get_tag()
        if sys.platform == "win32":
            return "py3", "none", platform
        return python, abi, platform


setup(cmdclass={"bdist_wheel": BundledWheel})