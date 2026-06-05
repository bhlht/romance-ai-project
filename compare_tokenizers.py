from transformers import AutoTokenizer
import os

repo_id = "TaeHak/korean-harlequin-romance-LoRA"
token = os.environ.get("HF_TOKEN")

print("--- Base Tokenizer ---")
base_tok = AutoTokenizer.from_pretrained("deepseek-ai/deepseek-llm-7b-base", trust_remote_code=True, token=token)
print(f"Base Size: {len(base_tok)}")

print("\n--- LoRA Tokenizer (Subfolder) ---")
try:
    lora_tok = AutoTokenizer.from_pretrained(repo_id, subfolder="final_model", trust_remote_code=True, token=token)
    print(f"LoRA Size: {len(lora_tok)}")
    
    # Check for specific added tokens
    added = lora_tok.get_added_vocab()
    print(f"Added tokens count: {len(added)}")
    if len(added) > 0:
        print("First 5 added tokens:", list(added.keys())[:5])
except Exception as e:
    print(f"Error loading LoRA tokenizer: {e}")
