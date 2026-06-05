from transformers import AutoTokenizer
import os

try:
    repo_id = "TaeHak/korean-harlequin-romance-LoRA"
    token = os.environ.get("HF_TOKEN")
    lora_tok = AutoTokenizer.from_pretrained(repo_id, subfolder="final_model", trust_remote_code=True, token=token)
    print(f"LORA_TOKENIZER_SIZE: {len(lora_tok)}")
except Exception as e:
    print("Error:", e)
