import os
import requests
import uuid
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
import warnings

# Suppress ebooklib warnings
warnings.filterwarnings('ignore')

def download_file(url: str, save_dir: str = "temp") -> str:
    """Downloads a file from a URL to a temporary path."""
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)
    
    # Generate unique filename to avoid collisions
    filename = f"{uuid.uuid4()}.epub"
    save_path = os.path.join(save_dir, filename)
    
    response = requests.get(url, stream=True)
    response.raise_for_status()
    
    with open(save_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
            
    return save_path

def epub_to_text(epub_path: str) -> str:
    """Extracts text from an EPUB file."""
    try:
        book = epub.read_epub(epub_path)
        text = []
        for item in book.get_items():
            if item.get_type() == ebooklib.ITEM_DOCUMENT:
                soup = BeautifulSoup(item.get_content(), 'html.parser')
                text.append(soup.get_text(separator='\n'))
        return "\n".join(text)
    except Exception as e:
        print(f"Error reading {epub_path}: {e}")
        return ""

def process_epub_from_url(url: str) -> str:
    """Downloads an EPUB from URL and returns its text content."""
    temp_path = download_file(url)
    try:
        text = epub_to_text(temp_path)
        return text
    finally:
        # Cleanup
        if os.path.exists(temp_path):
            os.remove(temp_path)
