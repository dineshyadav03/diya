"""How fast does the model read a ~3000-token prompt and write a few words? Calls the local Ollama directly with the model Diya uses; nothing is stored."""
import json
import random
import sys
import time
import urllib.request

random.seed(sys.argv[1] if len(sys.argv) > 1 else "x")
words = "river stone lantern copper window garden thread market violin harbor ladder pepper cloud anchor basket mirror velvet orchard".split()
text = " ".join(random.choice(words) + str(random.randint(0, 999)) for _ in range(2300))
body = json.dumps({"model": "diya-chat", "prompt": text + "\n\nSay only the word ready.", "stream": False, "options": {"num_predict": 8}, "keep_alive": "30m"}).encode()
started = time.time()
request = urllib.request.Request("http://127.0.0.1:11434/api/generate", body, {"Content-Type": "application/json"})
reply = json.loads(urllib.request.urlopen(request, timeout=1500).read())
took = time.time() - started
prompt_tokens, read_s = reply.get("prompt_eval_count", 0), reply.get("prompt_eval_duration", 0) / 1e9
wrote, write_s = reply.get("eval_count", 0), reply.get("eval_duration", 0) / 1e9
load_s = reply.get("load_duration", 0) / 1e9
print(f"total {took:.0f}s | load {load_s:.1f}s | read {prompt_tokens} tokens in {read_s:.1f}s = {prompt_tokens / read_s if read_s else 0:.0f} tok/s | wrote {wrote} tokens in {write_s:.1f}s = {wrote / write_s if write_s else 0:.1f} tok/s")
