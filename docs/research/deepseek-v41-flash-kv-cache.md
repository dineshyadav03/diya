# DeepSeek-V4.1-Flash: KV-cache compression

- **Source:** https://arxiv.org/abs/2609.19969 ("DeepSeek-V4.1-Flash: Pushing the Limits of KV Cache
  Compression", DeepSeek-AI, submitted 2026-09-17)
- **Noted:** 2026-09-21
- **Status:** a signal to track, not actionable now. Listed as entry 9 in [RESEARCH.md](../../RESEARCH.md).

## Facts

- 552B-parameter mixture-of-experts model. 16B parameters are active per token in decode and 8B in
  prefill. Context up to 1M tokens.
- CSA2 cross-layer KV reuse plus FP4 KV caching gives a global KV footprint of 890 bytes per token,
  about 1/4 of V4-Flash.
- SWA Bounded Replay cuts the persistent KV cache (SSD or host memory) to about 1/8 of V4-Flash.

Each figure above appears in the paper's abstract. The paper's methods and any independent
reproduction have not been reviewed here.

## Why it matters for Diya

Long-horizon agent workloads are getting cheaper on KV memory. These compression techniques are
likely to land in smaller local models and llama.cpp-style runtimes.

## Action

Track as a signal, not actionable now.
