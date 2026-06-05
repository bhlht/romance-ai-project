from transformers import AutoTokenizer
import os

repo_id = "TaeHak/korean-harlequin-romance-LoRA"
token = os.environ.get("HF_TOKEN")

try:
    print("--- Loading Tokenizer from final_model ---")
    tokenizer = AutoTokenizer.from_pretrained(repo_id, subfolder="final_model", trust_remote_code=True, token=token)
    print(f"EOS Token: '{tokenizer.eos_token}' (ID: {tokenizer.eos_token_id})")
    print(f"BOS Token: '{tokenizer.bos_token}' (ID: {tokenizer.bos_token_id})")
    print(f"PAD Token: '{tokenizer.pad_token}' (ID: {tokenizer.pad_token_id})")
    
    if tokenizer.eos_token_id is None:
        print("⚠️ Warning: EOS token is None! Repetition likely.")
        
except Exception as e:
    print(f"Error: {e}")
