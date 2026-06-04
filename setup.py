# Standard Library
import re

# Third Party
from setuptools import setup

with open("aareactions/__init__.py", "r", encoding="utf-8") as f:
    version = re.search(r'__version__ = "([^"]+)"', f.read()).group(1)

if __name__ == "__main__":
    setup(
        name="aa-reactions",
        version=version,
        packages=["aareactions"],
        include_package_data=True,
    )
