"""One real chat turn through Diya's own Agent and the real model, on a COPY of the database (nothing is saved to the real one). Prints the time and the answer."""
import dataclasses
import os
import shutil
import sys
import tempfile
import time

ROOT = "C:/Users/dines/OneDrive/Desktop/mac-mini-ai-engineer"
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import diya
import diya_config

tmp = tempfile.mkdtemp()
shutil.copy(ROOT + "/diya.db", tmp + "/copy.db")
config = dataclasses.replace(diya_config.load_config(), db_path=tmp + "/copy.db", connectors_log_path=tmp + "/c.log")
agent = diya.Agent(config)
for message in sys.argv[1:]:
    started = time.time()
    history = agent.with_profile([{"role": "user", "content": message}])
    answer, tools = agent.ask(history)
    print(f"{time.time() - started:6.1f}s  {message!r} -> tools {tools} -> {answer!r}")
shutil.rmtree(tmp, ignore_errors=True)
