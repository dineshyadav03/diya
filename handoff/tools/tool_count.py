"""Which of the tools sent on every turn are proposal tools that the turn would refuse anyway unless the message asked for them? Stand-in model, a copy of the database, nothing sent."""
import dataclasses
import json
import os
import shutil
import sys
import tempfile

ROOT = "C:/Users/dines/OneDrive/Desktop/mac-mini-ai-engineer"
sys.path.insert(0, ROOT)
sys.path.insert(0, ROOT + "/tests")
os.chdir(ROOT)

import diya
import diya_config
from fakes import FakeClient

tmp = tempfile.mkdtemp()
shutil.copy(ROOT + "/diya.db", tmp + "/copy.db")
config = dataclasses.replace(diya_config.load_config(), db_path=tmp + "/copy.db", connector_tokens_dir=ROOT + "/connector_tokens", connectors_log_path=tmp + "/c.log")
agent = diya.Agent(config, client=FakeClient([]))
by_tool = {kind.tool_name: kind for kind in agent.actions.kinds if kind.tool is not None}
everything = agent.tools
print("offered:", len(everything), "chars:", len(json.dumps(everything)))
print("proposal tools:", sum(1 for s in everything if s["function"]["name"] in by_tool), " with an `asked` gate:", sum(1 for s in everything if s["function"]["name"] in by_tool and by_tool[s["function"]["name"]].asked is not None))
for message in ("tell me a joke", "what is the capital of France", "what is on my calendar", "what am I doing next Tuesday?", "make a Drive folder called Diya smoke test", "remind me to call mum at 5pm", "what is the weather in Pune"):
    kept = [s for s in everything if s["function"]["name"] not in by_tool or by_tool[s["function"]["name"]].asked is None or by_tool[s["function"]["name"]].asked(message)]
    print(f"{message!r:46} {len(kept):2d} tools, {len(json.dumps(kept)) // 3:5d} ~tokens (was {len(json.dumps(everything)) // 3})")
print("always on:", [s["function"]["name"] for s in everything if s["function"]["name"] not in by_tool])
print("ungated proposals:", [n for n, k in by_tool.items() if k.asked is None])
shutil.rmtree(tmp, ignore_errors=True)
