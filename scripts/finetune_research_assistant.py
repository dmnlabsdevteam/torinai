#!/usr/bin/env python3
"""
Fine-tune obsidian3-autonomous-honest-merged with research assistant capabilities.
This creates the final production model: obsidian3-14b
"""

import subprocess
import sys
from pathlib import Path
from datetime import datetime

def run_command(cmd, description, log_file):
    """Run a command and print output."""
    print(f"\n{'='*60}")
    print(f"{description}")
    print(f"{'='*60}")
    print(f"Command: {' '.join(cmd)}\n")
    print(f"Logging to: {log_file}\n")

    with open(log_file, 'w') as log:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )

        for line in process.stdout:
            print(line, end='')
            log.write(line)
            log.flush()

        process.wait()

        if process.returncode != 0:
            print(f"\n✗ Error: Command failed with code {process.returncode}")
            sys.exit(1)

    print(f"\n✓ {description} completed successfully")
    return process

def main():
    print("=" * 60)
    print("RESEARCH ASSISTANT FINE-TUNING")
    print("=" * 60)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    print("Base Model: obsidian3-autonomous-honest-merged")
    print("Training Data: 23,578 research examples")
    print("Validation Data: 2,620 examples")
    print("Output Model: obsidian3-14b (production)")
    print()

    # Paths
    base_model = "/Users/stefan/TorinAI/core/models/obsidian3-autonomous-honest-merged"
    data_dir = "/Users/stefan/TorinAI/data/training/research_combined"
    adapter_output = "/Users/stefan/TorinAI/core/models/obsidian3-research-adapters"

    # Verify files exist
    if not Path(base_model).exists():
        print(f"✗ Error: Base model not found at {base_model}")
        sys.exit(1)

    if not Path(data_dir).exists():
        print(f"✗ Error: Data directory not found at {data_dir}")
        sys.exit(1)

    if not Path(f"{data_dir}/train.jsonl").exists():
        print(f"✗ Error: Training data not found at {data_dir}/train.jsonl")
        sys.exit(1)

    if not Path(f"{data_dir}/valid.jsonl").exists():
        print(f"✗ Error: Validation data not found at {data_dir}/valid.jsonl")
        sys.exit(1)

    print("✓ All files verified\n")

    # Fine-tuning parameters
    # Using more iterations for research capabilities
    iters = 800  # More iterations for comprehensive research training
    batch_size = 4
    learning_rate = 1e-5

    print("Training Configuration:")
    print(f"  Iterations: {iters}")
    print(f"  Batch Size: {batch_size}")
    print(f"  Learning Rate: {learning_rate}")
    print(f"  LoRA Rank: 8")
    print(f"  Gradient Checkpointing: Enabled")
    print()

    # Run fine-tuning
    finetune_cmd = [
        "mlx_lm.lora",
        "--model", base_model,
        "--train",
        "--data", data_dir,
        "--adapter-path", adapter_output,
        "--iters", str(iters),
        "--steps-per-eval", "50",
        "--steps-per-report", "10",
        "--batch-size", str(batch_size),
        "--learning-rate", str(learning_rate),
        "--grad-checkpoint"
    ]

    # Create log file path
    log_dir = Path("/Users/stefan/TorinAI/logs")
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"research_finetune_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    run_command(finetune_cmd, "Fine-tuning with research assistant data", str(log_file))

    print("\n" + "=" * 60)
    print("FINE-TUNING COMPLETE")
    print("=" * 60)
    print(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    print("LoRA adapters saved to:")
    print(f"  {adapter_output}")
    print()
    print("Next step: Merge adapters to create obsidian3-14b")
    print("Command: mlx_lm.fuse --model {base_model} --adapter-path {adapter_output} --save-path /Users/stefan/TorinAI/core/models/obsidian3-14b")

if __name__ == "__main__":
    main()
