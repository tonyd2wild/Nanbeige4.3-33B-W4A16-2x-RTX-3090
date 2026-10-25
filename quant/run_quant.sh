#!/usr/bin/env bash
# Nanbeige4.3-33B (chat) -> int4 W4A16 AutoRound on GPU0+1 (Tony 10-25 "begin the int4").
# Needs the 35B container stopped first (it owns GPU0+1). Output: /home/tony/models/nanbeige43-33b-w4a16-autoround
set -euo pipefail
mkdir -p /home/tony/nanbeige/hfcache
docker rm -f nanbeige-quant 2>/dev/null || true
docker run -d --name nanbeige-quant --restart no --gpus "\"device=0,1\"" --ipc host --shm-size 16g \
  -v /home/tony/models:/models -v /home/tony/nanbeige/hfcache:/root/.cache/huggingface \
  -e HF_HUB_DISABLE_XET=1 -e PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
  local/autoround:0.16.1 \
  auto-round --model /models/nanbeige43-33b-bf16 --scheme W4A16 --iters 100 --nsamples 128 --seqlen 2048 \
    --device_map 0,1 --format auto_gptq --output_dir /models/nanbeige43-33b-w4a16-autoround
echo launched; docker ps --filter name=nanbeige-quant --format "{{.Names}} {{.Status}}"
