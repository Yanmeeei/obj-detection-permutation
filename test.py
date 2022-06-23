import os
import sys
from simulatorv3 import Simulator

Simulator(
    dep_filename="dep.csv",
    prof_filenames=[
        "prof.csv",
        "prof.csv",
        # "prof.csv",
        # "prof.csv",
        # "prof.csv",
        # "prof.csv",
        # "prof.csv",
        # "prof.csv",
    ],
    bandwidth=1280,
    ignore_latency=False,
    detailed=False,
    feedback_interval=0.001,
)
