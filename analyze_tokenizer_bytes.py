from transformers import AutoTokenizer
import os

repo_id = "TaeHak/korean-harlequin-romance-LoRA"
token = os.environ.get("HF_TOKEN")

print("--- Loading Specialized Tokenizer ---")
try:
    tokenizer = AutoTokenizer.from_pretrained(repo_id, subfolder="final_model", trust_remote_code=True, token=token)
    print(f"Tokenizer Class: {type(tokenizer)}")
    print(f"Vocab Size: {len(tokenizer)}")
    
    test_text = "안녕"
    tokens = tokenizer.encode(test_text, add_special_tokens=False)
    print(f"Tokens for '{test_text}': {tokens}")
    for t in tokens:
        print(f"Token {t}: '{tokenizer.decode([t])}'")
        
    # Check if '넘얗게' can be decoded correctly
    alien_text = "넘얗게"
    alien_tokens = tokenizer.encode(alien_text, add_special_tokens=False)
    print(f"Tokens for '{alien_text}': {alien_tokens}")
    
except Exception as e:
    print(f"Error: {e}")
