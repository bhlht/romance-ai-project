import os
import torch
from datasets import load_dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TrainingArguments,
    logging,
)
from peft import LoraConfig
import argparse

import trl
print(f"TRL Version: {trl.__version__}")

# Configuration (defaults)
DEFAULT_MODEL_NAME = "deepseek-ai/deepseek-llm-7b-base"
DEFAULT_DATA_PATH = "data/combined_romance_data.txt"
DEFAULT_OUTPUT_DIR = "deepseek_finetuned_model"
MAX_SEQ_LENGTH = 2048

def train(model_name, data_path, output_dir):
    print(f"Loading model: {model_name}")
    
    # 1. Quantization Config
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
    )

    # 2. Load Model
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True
    )
    model.config.use_cache = False
    model.config.pretraining_tp = 1

    # 3. Load Tokenizer
    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    # 4. Load Dataset
    print(f"Loading data from {data_path}...")
    dataset = load_dataset("text", data_files={"train": data_path}, split="train")

    # Detect if we are on an Ampere GPU (A100) or newer to use bf16 (better performance/stability)
    use_bf16 = False
    if torch.cuda.is_available():
        major_version, _ = torch.cuda.get_device_capability()
        if major_version >= 8:
            print("Ampere GPU detected (A100/A10/A6000 etc). Enabling bf16.")
            use_bf16 = True
        else:
            print("Older GPU detected (V100/T4). Using fp16.")

    # 5. LoRA Config
    peft_config = LoraConfig(
        lora_alpha=16,
        lora_dropout=0.1,
        r=64,
        bias="none",
        task_type="CAUSAL_LM",
    )

    from trl import SFTTrainer, SFTConfig

    # 6. Training Arguments (using SFTConfig for latest TRL support)
    # Note: Some versions of TRL might have issues passing max_seq_length in init, so we set it manually if needed.
    training_args = SFTConfig(
        output_dir=output_dir,
        num_train_epochs=1,
        per_device_train_batch_size=4,
        gradient_accumulation_steps=1,
        optim="paged_adamw_32bit",
        save_steps=500,
        logging_steps=25,
        learning_rate=2e-4,
        weight_decay=0.001,
        fp16=not use_bf16,      # Use fp16 if bf16 is OFF
        bf16=use_bf16,          # Use bf16 if Ampere GPU (A100)
        max_grad_norm=0.3,
        max_steps=-1,
        warmup_ratio=0.03,
        group_by_length=True,
        lr_scheduler_type="constant",
        # REMOVED max_seq_length and packing from init to avoid TypeError in some versions
    )
    
    # Manually set TRL specific args to ensure compatibility
    training_args.max_seq_length = MAX_SEQ_LENGTH
    training_args.packing = False

    # 7. Trainer
    # Define formatting function to handle text column
    def formatting_prompts_func(example):
        return example['text']

    trainer = SFTTrainer(
        model=model,
        train_dataset=dataset,
        peft_config=peft_config,
        formatting_func=formatting_prompts_func,
        processing_class=tokenizer,
        args=training_args,
    )

    print("Starting training...")
    trainer.train()

    print(f"Training complete. Saving model to {output_dir}...")
    trainer.model.save_pretrained(output_dir)
    print("Done!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fine-tune DeepSeek 7B")
    parser.add_argument("--model_name", type=str, default=DEFAULT_MODEL_NAME)
    parser.add_argument("--data_path", type=str, default=DEFAULT_DATA_PATH)
    parser.add_argument("--output_dir", type=str, default=DEFAULT_OUTPUT_DIR)
    
    args = parser.parse_args()
    
    train(args.model_name, args.data_path, args.output_dir)
