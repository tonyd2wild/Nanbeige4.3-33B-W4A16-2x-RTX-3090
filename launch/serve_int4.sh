#!/usr/bin/env bash
# Test-serve Nanbeige4.3-33B int4 (our AutoRound W4A16) on GPU0+1, TP2, vLLM v0.27.1, port 8017.
# GPU0+1 normally belong to the 35B (qwen36-35b-a3b, docker start to restore). Tony 10-25.
set -euo pipefail
MODEL=/home/tony/models/nanbeige43-33b-w4a16
test -f "$MODEL/config.json" || { echo "no model at $MODEL" >&2; exit 3; }
docker rm -f nanbeige-int4 2>/dev/null || true
docker run -d --name nanbeige-int4 --restart no --gpus all --ipc host --network host \
  -e CUDA_VISIBLE_DEVICES=0,1 -e NCCL_P2P_LEVEL=NVL -e NCCL_CUMEM_ENABLE=0 \
  -v "$MODEL:/models/nanbeige:ro" -v /home/tony/.cache/vllm:/root/.cache/vllm \
  vllm/vllm-openai:v0.27.1 \
  --model /models/nanbeige --served-model-name nanbeige4.3-33b \
  --host 0.0.0.0 --port 8017 --tensor-parallel-size 2 --quantization gptq_marlin \
  --dtype float16 --max-model-len ${MAXLEN:-65536} --gpu-memory-utilization ${GMU:-0.92} \
  --kv-cache-dtype ${KV:-fp8_e5m2} --max-num-seqs ${SEQS:-8} --no-enable-prefix-caching \
  --reasoning-parser qwen3 --enable-auto-tool-choice --tool-call-parser qwen3_coder
echo launched
