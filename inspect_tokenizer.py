from transformers import AutoTokenizer, AutoModelForCausalLM
import torch
import os

def inspect():
    model_id = "deepseek-ai/deepseek-llm-7b-base"
    lora_id = "TaeHak/korean-harlequin-romance-LoRA"
    # Use HF token since the repo is private/gated
    hf_token = os.environ.get("HF_TOKEN")
    
    print(f"Inspecting BASE Tokenizer ({model_id})...")
    base_tok = AutoTokenizer.from_pretrained(model_id, token=hf_token, trust_remote_code=True)
    print(f"Base Vocab Size: {len(base_tok)}")
    
    print(f"\nInspecting LORA Tokenizer ({lora_id})...")
    try:
        lora_tok = AutoTokenizer.from_pretrained(lora_id, token=hf_token, trust_remote_code=True)
        print(f"LoRA Vocab Size: {len(lora_tok)}")
        
        # Compare
        if len(base_tok) != len(lora_tok):
            print(f"Vocab size difference! Base: {len(base_tok)}, LoRA: {len(lora_tok)}")
            
            # Find the new tokens
            base_vocab = base_tok.get_vocab()
            lora_vocab = lora_tok.get_vocab()
            new_tokens = [k for k in lora_vocab.keys() if k not in base_vocab]
            print(f"New tokens added in LoRA: {new_tokens}")
    except Exception as e:
        print(f"Failed to load LoRA tokenizer: {e}")

if __name__ == "__main__":
    inspect()
