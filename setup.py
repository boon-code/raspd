import sys
import os
import re
base_path = os.path.dirname(os.path.realpath(sys.argv[0]))
src_path = os.path.join(base_path, 'src')
from distutils.core import setup

main_file = os.path.join(src_path, "raspd.py")

rx = re.compile("__version__\\s*=\\s*[',\"]{1}([^\",^']*)[',\"]")

with open(main_file, 'r') as f:
    m = rx.search(f.read())

if m is not None:
    version = m.group(1)
else:
    version = "unknown"

setup(
    name = "raspd",
    version = version,
    scripts = ['src/raspd.py'],
    data_files = [('/etc/init.d', ['src/raspd'])],
    description = "Raspberry PI Daemon"
)
