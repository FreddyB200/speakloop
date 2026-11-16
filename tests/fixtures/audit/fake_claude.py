"""Fake `claude` executable for tests: replays canned envelopes, records its argv and stdin.

Controlled by FAKE_CLAUDE_DIR: files `response_1`, `response_2`, ... are printed in call
order (the last one repeats); a file named `sleep` makes it hang. Calls are recorded as
`call_N.json` ({"argv": [...], "stdin": "...", "cwd": "..."}).
"""

import json
import os
import sys
import time
from pathlib import Path

base = Path(os.environ["FAKE_CLAUDE_DIR"])
calls = sorted(base.glob("call_*.json"))
n = len(calls) + 1
(base / f"call_{n}.json").write_text(
    json.dumps(
        {
            "argv": sys.argv[1:],
            "stdin": sys.stdin.read(),
            "cwd": os.getcwd(),
            "env_keys": sorted(os.environ),
        }
    )
)
if (base / "sleep").exists():
    time.sleep(30)
responses = sorted(base.glob("response_*"), key=lambda p: int(p.name.split("_")[1]))
chosen = responses[min(n, len(responses)) - 1]
sys.stdout.write(chosen.read_text())
