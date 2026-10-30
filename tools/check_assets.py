#!/usr/bin/env python3
"""Host entry point for the same bounded preflight used by the guest data setup."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime.server_data_preflight import *

if __name__ == '__main__':
    raise SystemExit(main())
