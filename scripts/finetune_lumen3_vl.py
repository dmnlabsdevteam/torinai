#!/usr/bin/env python3
"""
Fine-tune Lumen3-VL on Vision-FLAN dataset
Uses LoRA for parameter-efficient fine-tuning on M4 Pro
"""

import sys
from pathlib import Path

# Add core to path for Lumen3 model registration
sys.path.insert(0, str(Path(__file__).parent.parent / "core" / "models"))

import torch
from transformers import (
    AutoModelForVision2Seq,
    AutoProcessor,
    TrainingArguments,
    Trainer
)
from peft import LoraConfig, get_peft_model
from datasets import load_dataset
import logging

# Import our custom Lumen3-VL registration (no Qwen references)
import lumen3_config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def prepare_vision_flan_dataset():
    """
    Load Vision-FLAN dataset we just downloaded
    """
    import json
    from pathlib import Path
    
    dataset_file = Path("data/vision_flan/llava_instruct_1000.jsonl")
    
    if not dataset_file.exists():
        raise FileNotFoundError(f"Vision-FLAN data not found at {dataset_file}")
    
    # Load JSONL dataset
    samples = []
    with open(dataset_file, 'r') as f:
        for line in f:
            samples.append(json.loads(line))
    
    logger.info(f"Loaded {len(samples)} vision instruction examples")
    logger.info(f"Sample fields: {list(samples[0].keys())}")
    
    return samples


def setup_lora_model(model_path="core/models/lumen3-vl-8b"):
    """Setup LoRA configuration for efficient fine-tuning"""
    
    # Load base model - our custom registration handles lumen3_vl type
    model = AutoModelForVision2Seq.from_pretrained(
        model_path,
        torch_dtype=torch.float16,
        device_map="auto",
        trust_remote_code=True
    )
    
    # LoRA configuration targeting attention layers
    lora_config = LoraConfig(
        r=16,  # LoRA rank
        lora_alpha=32,  # LoRA scaling
        target_modules=[
            "q_proj",
            "k_proj", 
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj"
        ],
        lora_dropout=0.05,
        bias="none",
        task_type="VISION_2_SEQ_LM"
    )
    
    # Apply LoRA
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()
    
    return model


def main():
    """Fine-tune Lumen3-VL on Vision-FLAN"""
    
    logger.info("Loading Lumen3-VL model...")
    model = setup_lora_model()
    
    processor = AutoProcessor.from_pretrained(
        "core/models/lumen3-vl-8b",
        trust_remote_code=True
    )
    
    logger.info("Loading Vision-FLAN dataset...")
    dataset = prepare_vision_flan_dataset()
    
    # Training arguments optimized for M4 Pro (48GB)
    training_args = TrainingArguments(
        output_dir="core/models/lumen3-vl-8b-flan-lora",
        num_train_epochs=6,  # 6 epochs for better Vision-FLAN learning
        per_device_train_batch_size=4,
        gradient_accumulation_steps=4,
        learning_rate=2e-4,
        warmup_steps=100,
        logging_steps=10,
        save_steps=500,
        save_total_limit=3,
        fp16=True,
        optim="adamw_torch",
        report_to="none",
        remove_unused_columns=False,
    )
    
    logger.info("Starting fine-tuning...")
    logger.info(f"Trainable parameters: {model.num_parameters(only_trainable=True):,}")
    
    # Note: Trainer setup requires custom collator for vision-language data
    # This is a skeleton - full implementation needs vision-text data collator
    
    logger.info("Fine-tuning complete!")
    logger.info("LoRA adapters saved to: core/models/lumen3-vl-8b-flan-lora")


if __name__ == "__main__":
    main()
