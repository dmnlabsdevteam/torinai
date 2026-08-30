.PHONY: start start-public status interactive quantum help setup health

# Python and host configuration
PY?=python3
HOST?=127.0.0.1
PORT?=8000

# Main commands using the ONE AND ONLY torin script
start:
	./torin start --host $(HOST) --port $(PORT)

start-public:
	./torin start --host 0.0.0.0 --port $(PORT)

stop:
	./torin stop

kill:
	./torin kill

status:
	./torin status

restart:
	./torin restart --host $(HOST) --port $(PORT)

interactive:
	./torin start --interactive

quantum:
	./torin start --mode quantum-only

help:
	./torin help

# Legacy commands for compatibility
setup:
	./deployments/scripts/setup-mac.sh

health:
	@curl -sS http://$(HOST):$(PORT)/health | sed 's/{/{\n  /;s/,/\n  ,/g;s/}/\n}/'

# Development tools
run:
	./start --mode full --host $(HOST) --port $(PORT) --verbose

run-public:
	./start --mode full --host 0.0.0.0 --port $(PORT) --verbose

# Convert Hugging Face model folder to GGUF
MODEL_DIR?=models/llama3-8b-instruct
GGUF_OUT?=$(MODEL_DIR)/llama3-8b-f16.gguf
convert-gguf:
	./deployments/scripts/convert-to-gguf.sh -m $(MODEL_DIR) -o $(GGUF_OUT)

# Quantize GGUF (requires building llama.cpp tools)
GGUF_IN?=$(GGUF_OUT)
GGUF_Q_OUT?=$(MODEL_DIR)/llama3-8b-Q4_K_M.gguf
QTYPE?=Q4_K_M
quantize-gguf:
	./deployments/scripts/quantize-gguf.sh -i $(GGUF_IN) -o $(GGUF_Q_OUT) -q $(QTYPE)
