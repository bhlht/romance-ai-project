import os
import pandas as pd
import requests
import argparse
from urllib.parse import urlparse, unquote

def download_epubs(excel_path: str, output_dir: str):
    """
    Reads an Excel file containing download links and downloads EPUB files.
    
    Args:
        excel_path (str): Path to the Excel file (must have a 'Link' column).
        output_dir (str): Directory to save downloaded files.
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Created directory: {output_dir}")

    try:
        df = pd.read_excel(excel_path, sheet_name='data')
    except Exception as e:
        print(f"Error reading Excel file: {e}")
        return

    if 'Link' not in df.columns:
        print("Error: Excel file must contain a 'Link' column.")
        return

    links = df['Link'].dropna().unique()
    print(f"Found {len(links)} links to download.")

    failed_links = []
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    for i, link in enumerate(links):
        try:
            response = requests.get(link, stream=True, headers=headers, timeout=15)
            response.raise_for_status()

            # Try to get filename from content-disposition
            filename = None
            cd = response.headers.get('content-disposition')
            if cd:
                fname = cd.split('filename=')[1]
                if fname:
                    filename = unquote(fname).strip('"')
            
            # Fallback to URL path
            if not filename:
                parsed_url = urlparse(link)
                filename = os.path.basename(parsed_url.path)
            
            # Final fallback
            if not filename or not filename.lower().endswith('.epub'):
                filename = f"novel_{i+1}.epub"

            # Clean filename
            filename = "".join([c for c in filename if c.isalpha() or c.isdigit() or c in "._- "]).strip()

            save_path = os.path.join(output_dir, filename)
            
            if os.path.exists(save_path):
                print(f"Skipping existing file: {filename}")
                continue

            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            print(f"[{i+1}/{len(links)}] Downloaded: {filename}")
            
        except Exception as e:
            error_msg = str(e).split('\n')[0] # Keep it short
            print(f"[{i+1}/{len(links)}] Failed: {link} || Error: {error_msg}")
            failed_links.append({'Link': link, 'Error': error_msg})

    if failed_links:
        failed_df = pd.DataFrame(failed_links)
        failed_csv = os.path.join(output_dir, "failed_downloads.csv")
        failed_df.to_csv(failed_csv, index=False)
        print(f"\nCompleted with errors. {len(failed_links)} failed links saved to {failed_csv}")
    else:
        print("\nAll downloads completed successfully.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download EPUBs from Excel links.")
    parser.add_argument("--excel_file", type=str, default="epub_download_links.xlsx", help="Path to the Excel file.")
    parser.add_argument("--output_dir", type=str, default="data/epubs", help="Output directory for EPUBs.")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.excel_file):
        print(f"Excel file not found: {args.excel_file}")
    else:
        download_epubs(args.excel_file, args.output_dir)
