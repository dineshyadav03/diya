"""How big is the request one ordinary chat turn sends to the model? Runs on a COPY of the real database and a stand-in model; sends nothing anywhere."""
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
from fakes import FakeClient, text_reply

tmp = tempfile.mkdtemp()
shutil.copy(ROOT + "/diya.db", tmp + "/copy.db")
real = diya_config.load_config()
config = dataclasses.replace(real, db_path=tmp + "/copy.db", connector_tokens_dir=ROOT + "/connector_tokens", connectors_log_path=tmp + "/c.log")
for message in ("tell me a joke", "what am I doing next Tuesday?", "what is the capital of France"):
    client = FakeClient([text_reply("ok")] * 6)
    try:
        agent = diya.Agent(config, client=client)
        agent.ask([{"role": "user", "content": message}])
    except Exception as error:
        print(message, "->", type(error).__name__, str(error)[:150])
    for index, call in enumerate(client.chat_calls):
        msgs = json.dumps(call["messages"], ensure_ascii=False)
        tools = json.dumps(call["tools"], ensure_ascii=False) if call["tools"] else ""
        print(f"{message!r:36} call {index}: messages {len(msgs):6d} chars, tools {len(call['tools'] or [])} ({len(tools):6d} chars), ~tokens {(len(msgs) + len(tools)) // 4}")
shutil.rmtree(tmp, ignore_errors=True)
