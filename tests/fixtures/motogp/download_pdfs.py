#!/usr/bin/env python3
"""Download the MotoGP timing-sheet fixtures the tests need.

The Analysis PDF is required by the timing-parser and end-to-end tests. It is
NOT committed to the repository because MotoGP timing sheets are copyright Dorna
and their notice forbids redistribution:

    "These data/results cannot be reproduced, stored and/or transmitted ...
    without the previous express consent by the copyright owner." (c) DORNA

This script fetches them directly from the official source
(resources.motogp.com) into this directory for local testing only. Do not
commit or redistribute the downloaded files. Delete them when you are done if
you prefer.
"""

import os
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))

# (filename, official URL)
FILES = [
    ("THA_2025_MotoGP_RAC_Analysis.pdf",
     "https://resources.motogp.com/files/results/2025/THA/MotoGP/RAC/Analysis.pdf"),
    ("THA_2025_MotoGP_RAC_LapChart.pdf",
     "https://resources.motogp.com/files/results/2025/THA/MotoGP/RAC/LapChart.pdf"),
]


def main():
    print(__doc__)
    for name, url in FILES:
        dest = os.path.join(HERE, name)
        if os.path.exists(dest):
            print(f"  already present: {name}")
            continue
        print(f"  downloading {name} ...")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        with open(dest, "wb") as handle:
            handle.write(data)
        print(f"    saved {len(data):,} bytes")
    print("\nDone. These files are Dorna copyright — local use only.")


if __name__ == "__main__":
    main()
