# Does the laptop's graphics chip speed Diya up? What was found on 2026-10-21 (task DIYA-192)

The sheet asks: *"Report whether Intel GPU actually accelerates current runtime."* The honest report so far is **"it is not used, and whether using it would help has not been measured"**. What was read, and what is left to do:

## What was observed (read from this computer on 2026-10-21; nothing was changed)

| Fact | Where it came from |
|---|---|
| Ollama 0.40.6 | `ollama --version` |
| Processor: Intel Core Ultra 7 155H, 16 cores, 22 threads | Windows system information |
| Graphics: Intel Arc Graphics (integrated), driver 32.0.101.8991, about 4 GB reported | Windows system information |
| Memory: 15.7 GB in total; the log line written when Ollama last started says "available=1.2 GiB" | Windows; Ollama's `server.log` |
| Ollama found the graphics chip through Vulkan and **dropped it**: `dropping integrated GPU; to enable, set OLLAMA_IGPU_ENABLE=1` (library=Vulkan, "Intel(R) Arc(TM) Graphics") | Ollama's `server.log` |
| Ollama then ran on the processor: `inference compute id=cpu library=cpu` | Ollama's `server.log` |
| No model was loaded at the moment of looking (`ollama ps` empty), so no per-model "processor" column could be read | `ollama ps` |

So today every answer is computed on the processor. Ollama's own default is to ignore an integrated graphics chip, because it shares the computer's memory and often is not faster.

## What was NOT done, and why

* **Not measured whether switching it on helps.** That needs `OLLAMA_IGPU_ENABLE=1` set for Ollama and the Ollama server restarted, then the same prompts timed both ways. It restarts the model server the owner is using, loads a model into memory that is already nearly full (1.2 GiB free at the last start), and was on the owner's list as an open yes-or-no. It was therefore left for the owner to say yes to.
* **Not established** whether the Vulkan path is stable with the models Diya uses (`diya-chat`, the 3B-4B family, and the embedding model), or whether the answers stay the same.

## What a fair measurement would be (for when the owner agrees)

1. Quit other programs so the memory figure is the same both times; note the free memory before each run (the Status page's "This computer" line gives it).
2. With the default setup, time the same ten prompts three times each: the first token and the whole answer (the bake-off harness in `docs/MODEL_BENCHMARK.md` does this).
3. Set `OLLAMA_IGPU_ENABLE=1` (a user environment variable), restart Ollama, and repeat. Read `ollama ps` for the "processor" column and the server log for which device was used.
4. Keep it only if the whole-answer time improves **and** the answers on the nine evals stay the same; otherwise remove the variable again. Nothing about it is permanent either way.

This is the sheet's DIYA-193 and DIYA-194 done on one setting at a time. DIYA-192 stays **In progress** until it has been run.
