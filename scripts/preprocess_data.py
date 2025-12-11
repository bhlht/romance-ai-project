import os
import argparse
import glob
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
import warnings

# Suppress ebooklib warnings
warnings.filterwarnings('ignore')

def epub_to_text(epub_path):
    """Extracts text from an EPUB file."""
    try:
        book = epub.read_epub(epub_path)
        text = []
        for item in book.get_items():
            if item.get_type() == ebooklib.ITEM_DOCUMENT:
                # Use BS4 to strip HTML tags
                soup = BeautifulSoup(item.get_content(), 'html.parser')
                text.append(soup.get_text(separator='\n'))
        return "\n".join(text)
    except Exception as e:
        print(f"Error reading {epub_path}: {e}")
        return ""

def preprocess_data(input_dir, output_file):
    """
    Reads all EPUBs in input_dir, extracts text, cleans it, 
    and saves to output_file with [END_OF_NOVEL] separator.
    """
    epub_files = glob.glob(os.path.join(input_dir, "*.epub"))
    print(f"Found {len(epub_files)} EPUB files in {input_dir}")

    total_novels = 0
    
    with open(output_file, 'w', encoding='utf-8') as outfile:
        for epub_path in epub_files:
            print(f"Processing: {os.path.basename(epub_path)}...")
            raw_text = epub_to_text(epub_path)
            
            if len(raw_text.strip()) < 100: # Skip empty or too short files
                print(" -> Skipped (Content too short)")
                continue

            # Basic Cleaning
            cleaned_text = raw_text.replace('\r\n', '\n')
            # Remove excessive newlines
            while '\n\n\n' in cleaned_text:
                cleaned_text = cleaned_text.replace('\n\n\n', '\n\n')
            
            # Write to file
            outfile.write(cleaned_text)
            outfile.write("\n\n[END_OF_NOVEL]\n\n")
            total_novels += 1
            
    print(f"\nPreprocessing Complete. {total_novels} novels saved to {output_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Preprocess EPUBs to Text")
    parser.add_argument("--input_dir", type=str, default="data/epubs", help="Directory containing EPUB files")
    parser.add_argument("--output_file", type=str, default="data/combined_romance_data.txt", help="Output text file path")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.input_dir):
        print(f"Input directory not found: {args.input_dir}")
    else:
        # Install dependencies if missing handled by requirements? 
        # User might need: pip install EbookLib beautifulsoup4
        preprocess_data(args.input_dir, args.output_file)
