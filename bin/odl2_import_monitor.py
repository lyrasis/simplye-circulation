#!/usr/bin/env python
"""Update the circulation manager server with new books from
OPDS 2.x + ODL collections."""
import os
import sys

from api.odl2 import ODL2Importer, ODL2ImportMonitor, ODL2API
from core.scripts import OPDSImportScript

bin_dir = os.path.split(__file__)[0]
package_dir = os.path.join(bin_dir, "..")
sys.path.append(os.path.abspath(package_dir))

import_script = OPDSImportScript(
    importer_class=ODL2Importer,
    monitor_class=ODL2ImportMonitor,
    protocol=ODL2API.NAME
)

import_script.run()
