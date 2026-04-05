bash scripts/run-openclaw-gateway-governance-e2e.sh   --stable-run-dir   --demo-probe   --demo-case approval   --approval-mode llm --ollama-model qwen3:4b

bash scripts/run-openclaw-gateway-governance-e2e.sh   --stable-run-dir   --demo-probe   --demo-cdc   --demo-case approval   --approval-mode llm --ollama-model qwen3:4b

rm -rf .tmp/openclaw-gateway-e2e/current && \
bash scripts/run-openclaw-gateway-governance-e2e.sh \
  --stable-run-dir \
  --demo-probe \
  --demo-cdc \
  --demo-case approval \
  --approval-mode llm \
  --ollama-model gemma4:e2b

rm -rf .tmp/openclaw-gateway-e2e/current && \
bash scripts/run-openclaw-gateway-governance-e2e.sh \
  --stable-run-dir \
  --demo-probe \
  --demo-cdc \
  --demo-case approval \
  --approval-mode llm \
  --ollama-model qwen3:4b