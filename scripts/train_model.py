import shutil
import zipfile
import time
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


# Configuration (defaults)
DEFAULT_MODEL_NAME = "deepseek-ai/deepseek-llm-7b-base"
DEFAULT_DATA_PATH = "data/combined_romance_data.txt"
DEFAULT_OUTPUT_DIR = "deepseek_finetuned_model"
MAX_SEQ_LENGTH = 2048


def setup_data(data_path):
    """
    If data_path is a zip file, copy it to a temp local dir and unzip it.
    This drastically speeds up loading on Colab compared to reading from Drive.
    """
    if data_path.endswith(".zip"):
        print(f"Detected ZIP file: {data_path}")
        
        # Define local temp paths
        local_zip_path = "/content/temp_data.zip"
        local_extract_path = "/content/temp_data_extracted"
        
        # Clean up previous runs if needed
        if os.path.exists(local_zip_path):
            os.remove(local_zip_path)
        if os.path.exists(local_extract_path):
            shutil.rmtree(local_extract_path)
            
        print(f"Copying {data_path} to {local_zip_path} (local disk)...")
        start_time = time.time()
        shutil.copy(data_path, local_zip_path)
        print(f"Copy took {time.time() - start_time:.2f} seconds.")
        
        print(f"Unzipping to {local_extract_path}...")
        start_time = time.time()
        with zipfile.ZipFile(local_zip_path, 'r') as zip_ref:
            zip_ref.extractall(local_extract_path)
        print(f"Unzip took {time.time() - start_time:.2f} seconds.")
        
        # Find the text file inside (assuming single file or specific structure)
        # For this logic, we'll try to find the first likely text file or return the dir
        # If the user's zip contains the txt exactly:
        extracted_files = [
            os.path.join(dp, f) 
            for dp, dn, filenames in os.walk(local_extract_path) 
            for f in filenames 
            if f.endswith('.txt') or f.endswith('.json')
        ]
        
        if extracted_files:
            print(f"Using extracted file: {extracted_files[0]}")
            return extracted_files[0]
        else:
            print(f"Warning: No .txt/.json found in zip. Using directory: {local_extract_path}")
            return local_extract_path

    return data_path

def train(model_name, data_path, output_dir):
    print(f"Loading model: {model_name}")
    
    # 0. Setup Data (Handle Zip for Colab speedup)
    final_data_path = setup_data(data_path)
    
    # 0.1 Setup Persistent Cache
    # Use a cache dir inside output_dir (which is on Drive) to avoid re-tokenizing every time
    cache_dir = os.path.join(output_dir, "cache_huggingface")
    os.makedirs(cache_dir, exist_ok=True)
    os.environ["HF_DATASETS_CACHE"] = cache_dir
    print(f"Using persistent cache dir: {cache_dir}")
    
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
    print(f"Loading data from {final_data_path}...")
    dataset = load_dataset("text", data_files={"train": final_data_path}, split="train")

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

        save_steps=50,  # Save more frequently (every 50 steps) to prevent data loss on disconnect
        save_total_limit=2, # Keep only the last 2 checkpoints to save Drive space
        logging_steps=10,
        learning_rate=2e-4,
        weight_decay=0.001,
        fp16=not use_bf16,      # Use fp16 if bf16 is OFF
        bf16=use_bf16,          # Use bf16 if Ampere GPU (A100)
        max_grad_norm=0.3,
        max_steps=-1,
        warmup_ratio=0.03,
        group_by_length=True,
        lr_scheduler_type="constant",
        report_to="none",  # Disable wandb/mlflow logging to prevent interactive prompts
        dataset_num_proc=4, # Reduced from os.cpu_count() to prevent RAM OOM on large datasets (17M+)
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
    
    # Check for existing checkpoints to resume from
    last_checkpoint = None
    if os.path.exists(output_dir):
        checkpoints = [d for d in os.listdir(output_dir) if d.startswith("checkpoint-")]
        if checkpoints:
            checkpoints.sort(key=lambda x: int(x.split("-")[1]))
            last_checkpoint = os.path.join(output_dir, checkpoints[-1])
            print(f"Resuming from checkpoint: {last_checkpoint}")
    
    try:
        trainer.train(resume_from_checkpoint=last_checkpoint)
        print("Training finished successfully.")
    except Exception as e:
        print(f"Training interrupted or errored: {e}")
        # Re-raise unless you want to suppress specific errors
        raise e
    finally:
        # 8. Force Save on Exit (Connects to user request for robustness)
        print(f"Saving model state to {output_dir} (finally block)...")
        trainer.model.save_pretrained(output_dir)
        tokenizer.save_pretrained(output_dir)
        print("Model and tokenizer saved.")

    print("Done!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fine-tune DeepSeek 7B")
    parser.add_argument("--model_name", type=str, default=DEFAULT_MODEL_NAME)
    parser.add_argument("--data_path", type=str, default=DEFAULT_DATA_PATH)
    parser.add_argument("--output_dir", type=str, default=DEFAULT_OUTPUT_DIR)
    
    args = parser.parse_args()
    
    train(args.model_name, args.data_path, args.output_dir)
