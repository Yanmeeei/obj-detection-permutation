import os
import sys
from simulatorv2 import Simulator

Simulator(
    dep_filename="dep.csv",
    prof_filenames=[
        "prof.csv",
        "prof.csv",
        "prof.csv",
        # "prof.csv",
        # "prof.csv",
        # "prof.csv",
        # "prof.csv",
        # "prof.csv",
    ],
    bandwidth=800,
    ignore_latency=False,
)
