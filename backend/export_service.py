import os
import zipfile
import io
import re
from ebooklib import epub

class ExportService:
    def _remove_project_plan(self, text: str) -> str:
        """
        Removes 'Story Setup' or 'Project Plan' section.
        Assumes the real story starts with [Chapter ...], ## ..., or [Prologue].
        """
        # Patterns for Story Start
        # 1. [Chapter 1], [Prologue]
        # 2. ## 1. Title, ## Prologue
        # 3. 제1장, 제 1 장
        start_pattern = re.compile(r"(?:^|\n)(\[Chapter|\[Prologue|##\s?\d|##\s?Prologue|제\s?\d+\s?장)", re.IGNORECASE)
        match = start_pattern.search(text)
        
        if match:
            # Found the start of the story body. 
            # Check if the match is at the very beginning (index 0 or near 0). 
            # If so, nothing to remove. 
            # If deeper, remove everything before this match.
            start_index = match.start(1) if match.start(1) >= 0 else match.start()
            return text[start_index:].strip()
            
        return text

    def get_clean_text(self, text: str) -> str:
        return self._remove_project_plan(text)

    def split_text_for_serialization(self, text: str, target_chars: int = 2000) -> list[str]:
        """
        Splits text into episodes of approximately 'target_chars' length.
        - Removes Project Plan / Story Setup first.
        - Removes existing Chapter headers (e.g., [Chapter 1], ## 1. Title).
        - Splits at the nearest paragraph break to avoid cutting sentences.
        """
        # 0. Remove Project Plan
        text = self._remove_project_plan(text)

        # 1. Clean Headers
        # Remove lines starting with [Chapter, ##, or Chapter
        clean_text = re.sub(r'(?m)^(?:\[?Chapter\s?\d+\]?|##\s?\d+\.?|제\s?\d+\s?장).*$', '', text)
        # Remove multiple newlines
        clean_text = re.sub(r'\n{3,}', '\n\n', clean_text).strip()
        
        episodes = []
        current_pos = 0
        total_len = len(clean_text)
        
        while current_pos < total_len:
            end_pos = current_pos + target_chars
            
            if end_pos >= total_len:
                episodes.append(clean_text[current_pos:])
                break
            
            # Find nearest paragraph break (newline) within a reasonable range (e.g., +/- 500 chars)
            # We look forward first, then backward
            search_window = clean_text[end_pos - 500 : end_pos + 500] if end_pos + 500 < total_len else clean_text[end_pos - 500:]
            
            # Try to find double newline (paragraph break) first
            relative_break = search_window.rfind('\n\n')
            if relative_break == -1:
                relative_break = search_window.rfind('\n') # Fallback to single newline
            
            if relative_break != -1:
                # Calculate absolute split position
                # The search window starts at end_pos - 500
                split_point = (end_pos - 500) + relative_break
                
                # Ensure we make progress
                if split_point <= current_pos:
                     split_point = end_pos # Force split if no natural break found
                
                episodes.append(clean_text[current_pos:split_point].strip())
                current_pos = split_point
            else:
                # No newline found? Just split at target
                episodes.append(clean_text[current_pos:end_pos].strip())
                current_pos = end_pos
                
        return episodes

    def create_epub(self, title: str, author: str, content: str, cover_image_path: str = None, publisher: str = None) -> io.BytesIO:
        """
        Creates a single EPUB file from the content.
        """
        # 0. Clean Content (Remove Plan)
        content = self._remove_project_plan(content)

        book = epub.EpubBook()
        book.set_identifier(f'{title}-{author}')
        book.set_title(title)
        book.set_language('ko')
        book.add_author(author)
        if publisher:
            book.add_metadata('DC', 'publisher', publisher)
        
        # Cover
        if cover_image_path and os.path.exists(cover_image_path):
            with open(cover_image_path, 'rb') as f:
                book.set_cover("cover.png", f.read())
        
        # Content (Simple Chapter 1 for full text)
        c1 = epub.EpubHtml(title='Start', file_name='chap_01.xhtml', lang='ko')
        # specific css wrapper if needed
        c1.content = f'<h1>{title}</h1><p>{content.replace(chr(10), "</p><p>")}</p>'
        
        book.add_item(c1)
        
        # Define Table Of Contents
        book.toc = (epub.Link('chap_01.xhtml', 'Start', 'start'), )
        
        # Add default NCX and Nav file
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        
        # Basic CSS
        style = 'body { font-family: "Noto Sans KR", sans-serif; } p { margin-bottom: 1em; }'
        nav_css = epub.EpubItem(uid="style_nav", file_name="style/nav.css", media_type="text/css", content=style)
        book.add_item(nav_css)
        
        # Spine
        book.spine = ['nav', c1]
        
        # Output to buffer
        buffer = io.BytesIO()
        epub.write_epub(buffer, book, {})
        buffer.seek(0)
        return buffer

    def create_serial_zip(self, episodes: list[str], title: str, author: str, publisher: str = None, format_type='txt') -> io.BytesIO:
        """
        Creates a ZIP file containing split episodes.
        format_type: 'txt' or 'epub'
        """
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for i, text in enumerate(episodes):
                filename = f"Episode_{i+1:03d}.{format_type}"
                
                if format_type == 'txt':
                    zf.writestr(filename, text)
                elif format_type == 'epub':
                    # Create mini-epub for this episode
                    epub_buffer = self.create_epub(f"{title} - Episode {i+1}", author, text, publisher=publisher)
                    zf.writestr(filename, epub_buffer.getvalue())
                    
        zip_buffer.seek(0)
        return zip_buffer

export_service = ExportService()
