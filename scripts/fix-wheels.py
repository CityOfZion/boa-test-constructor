"""
This script is a helper script to correctly rename wheels.

While the boaconstructor package is all in Python, it relies on a platform specific executable (neo-go) in the background.
The CI setup will build the platform specific neo-go executable and place it in the correct directory where it will be
picked up when packaging. `python -m build` creates a universal wheel and that needs to be fixed to include the correct
platform tag before uploading to PyPi. This cannot be done by simply renaming the file, it also does internal changes in
the wheel hence this script.
"""
import sys
import pathlib
import sysconfig
from wheel.cli.tags import tags


def main(wheel_dir):
    platform_tag = sysconfig.get_platform().replace("-", "_").replace(".", "_")
    for f in pathlib.Path(wheel_dir).glob("**/*"):
        if f.name.endswith("any.whl"):
            tags(str(f.absolute()), None, None, platform_tag, None, True)


if __name__ == "__main__":
    main(sys.argv[1])
