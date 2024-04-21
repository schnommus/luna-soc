#
# This file is part of LUNA.
#
# Copyright (c) 2023 Great Scott Gadgets <info@greatscottgadgets.com>
# SPDX-License-Identifier: BSD-3-Clause

"""Generate Rust support files for SoC designs."""

from .introspect import Introspect

from lambdasoc.soc.cpu import CPUSoC

import datetime
import logging

class GenRust:
    def __init__(self, soc: CPUSoC):
        self._soc = soc

    # - memory.x generation ---------------------------------------------------
    def generate_memory_x(self, file=None):
        """ Generate a memory.x file for the given SoC"""

        def emit(content):
            """ Utility function that emits a string to the targeted file. """
            print(content, file=file)

        # warning header
        emit("/*")
        emit(" * Automatically generated by LUNA; edits will be discarded on rebuild.")
        emit(" * (Most header files phrase this 'Do not edit.'; be warned accordingly.)")
        emit(" *")
        emit(f" * Generated: {datetime.datetime.now()}.")
        emit(" */")
        emit("")

        # memory regions
        regions = set()
        emit("MEMORY {")
        for window, (start, stop, ratio) in self._soc.memory_map.windows():
            if window.name not in ["bootrom", "scratchpad", "mainram", "hyperram"]:
                logging.debug("Skipping non-memory resource: {}".format(window.name))
                continue
            emit(f"    {window.name} : ORIGIN = 0x{start:08x}, LENGTH = 0x{stop-start:08x}")
            regions.add(window.name)
        emit("}")
        emit("")

        # region aliases
        ram = "mainram" if "mainram" in regions else "scratchpad"
        aliases = {
            "REGION_TEXT":   ram,
            "REGION_RODATA": ram,
            "REGION_DATA":   ram,
            "REGION_BSS":    ram,
            "REGION_HEAP":   ram,
            "REGION_STACK":  ram,
        }
        for alias, region in aliases.items():
            emit(f"REGION_ALIAS(\"{alias}\", {region});")
