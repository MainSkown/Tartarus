"""Stand-ins for the CAPE modules the host auxiliary imports, so it runs in tests without CAPE."""

import sys
import types


class Auxiliary:
    """The attributes CAPE's `lib.cuckoo.common.abstracts.Auxiliary` hands every module."""

    def __init__(self):
        self.task = None
        self.machine = None
        self.options = None


def stub_cape_modules() -> None:
    if "lib.cuckoo.common.abstracts" in sys.modules:
        return
    modules = {
        "lib": types.ModuleType("lib"),
        "lib.cuckoo": types.ModuleType("lib.cuckoo"),
        "lib.cuckoo.common": types.ModuleType("lib.cuckoo.common"),
        "lib.cuckoo.common.abstracts": types.ModuleType("lib.cuckoo.common.abstracts"),
        "lib.cuckoo.common.constants": types.ModuleType("lib.cuckoo.common.constants"),
    }
    modules["lib.cuckoo.common.abstracts"].Auxiliary = Auxiliary
    modules["lib.cuckoo.common.constants"].CUCKOO_ROOT = "/opt/CAPEv2"
    sys.modules.update(modules)
