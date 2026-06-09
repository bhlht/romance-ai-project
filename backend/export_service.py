import os
import zipfile
import io
import re
from ebooklib import epub
from ebooklib.epub import NAMESPACES
import ebooklib.epub

# Monkeypatch EpubWriter._write_opf to support EPUB 2.0 and avoid nav.xhtml generation
def _patched_write_opf(self):
    epub_version = getattr(self.book, 'epub_version', '3.0') or '3.0'
    package_attributes = {
        "xmlns": NAMESPACES["OPF"],
        "unique-identifier": self.book.IDENTIFIER_ID,
        "version": epub_version,
    }
    if self.book.direction and self.options["package_direction"]:
        package_attributes["dir"] = self.book.direction

    root = ebooklib.epub.etree.Element("package", package_attributes)

    prefixes = ["rendition: http://www.idpf.org/vocab/rendition/#"] + self.book.prefixes
    root.attrib["prefix"] = " ".join(prefixes)

    # METADATA
    self._write_opf_metadata(root)

    # MANIFEST
    _ncx_id = self._write_opf_manifest(root)

    # SPINE
    self._write_opf_spine(root, _ncx_id)

    # GUIDE
    self._write_opf_guide(root)

    # BINDINGS
    self._write_opf_bindings(root)

    # WRITE FILE
    self._write_opf_file(root)

ebooklib.epub.EpubWriter._write_opf = _patched_write_opf

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
        return text.strip()

    def _clean_style_tags(self, text: str) -> str:
        """
        Removes style markup tags (<STYLE> and </STYLE>) from the final exported draft.
        """
        if not text:
            return ""
        # Strip case-insensitive <STYLE> and </STYLE> tags
        text = re.sub(r'(?i)</?style>', '', text)
        # Also replace visual sparkles formatting markers in text if any
        text = text.replace("✨", "")
        return text
            
        return text

    def clean_chapter_title_text(self, text: str) -> str:
        """
        ### **제 1화... 처럼 마크다운 기호가 섞인 챕터 헤더를 정제하여 깔끔한 챕터 제목 반환
        """
        if not text:
            return ""
        # 앞뒤 마크다운 기호 (#, *, :, [ 등) 제거
        cleaned = re.sub(r'^[\s#*\[\]:]+|[\s#*\[\]:]+$', '', text)
        return cleaned.strip()

    def clean_text_header(self, text: str, title: str) -> str:
        """
        본문 첫줄에 프로젝트명이나 소설 제목이 단독 행으로 존재할 때 제거.
        """
        if not text:
            return ""
        lines = text.split('\n')
        cleaned_lines = []
        skip_header = True
        
        # 프로젝트명 형식 및 타이틀 매칭용 정규식
        proj_pattern = re.compile(r'^(?:My_Romance_\d+|' + re.escape(title) + r')$', re.IGNORECASE)
        
        for line in lines:
            stripped = line.strip()
            if not stripped:
                cleaned_lines.append(line)
                continue
            if skip_header:
                if proj_pattern.match(stripped):
                    continue
                else:
                    skip_header = False
            cleaned_lines.append(line)
            
        return '\n'.join(cleaned_lines)

    def _clean_chapter_title_from_body(self, ch_text: str, ch_title: str) -> str:
        """
        본문 텍스트 내에서 파싱되어 첫 줄에 기입되어 있을 수 있는 챕터 제목 문자열을 제거
        """
        if not ch_text:
            return ""
        lines = ch_text.split('\n')
        cleaned_lines = []
        title_skipped = False
        
        # 제목 단순화 (비교용)
        title_norm = re.sub(r'[^a-zA-Z0-9가-힣]', '', ch_title).lower() if ch_title else ""
        
        # 정교한 챕터 헤더 패턴 정의
        header_pattern = re.compile(r'^(?:##+|\[?Chapter|\[?Prologue|제\s*\d+\s*[화장]|프롤로그)', re.IGNORECASE)
        
        for line in lines:
            stripped = line.strip()
            if not stripped:
                cleaned_lines.append(line)
                continue
            
            if not title_skipped:
                line_norm = re.sub(r'[^a-zA-Z0-9가-힣]', '', stripped).lower()
                
                is_header = header_pattern.match(stripped) is not None
                contains_title = (title_norm and (title_norm in line_norm or line_norm in title_norm))
                is_num_title = re.match(r'^제\s*\d+\s*[화장]', stripped) is not None
                
                if is_header or contains_title or is_num_title:
                    title_skipped = True
                    continue
                else:
                    title_skipped = True
            
            cleaned_lines.append(line)
            
        return '\n'.join(cleaned_lines)

    def get_clean_text(self, text: str) -> str:
        clean = self._remove_project_plan(text)
        return self._clean_style_tags(clean)

    def format_body_paragraphs(self, text: str) -> str:
        if not text:
            return ""
        lines = text.split('\n')
        formatted = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                formatted.append("<p><br/></p>")
                continue
            if re.match(r'^\s*\*[\s*]*\*\s*$', stripped) or stripped == '***':
                formatted.append(f'<p class="center">{stripped}</p>')
            else:
                formatted.append(f'<p>{line}</p>')
        return '\n'.join(formatted)

    def split_text_for_serialization(self, text: str, target_chars: int = 2000) -> list[str]:
        """
        Splits text into episodes of approximately 'target_chars' length.
        - Removes Project Plan / Story Setup first.
        - Removes existing Chapter headers (e.g., [Chapter 1], ## 1. Title).
        - Splits at the nearest paragraph break to avoid cutting sentences.
        """
        # 0. Remove Project Plan
        text = self._remove_project_plan(text)
        text = self._clean_style_tags(text)

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

    def create_epub(self, title: str, author: str, content: str, cover_image_path: str = None, publisher: str = None, volumes: list = None, show_chapter_title_in_body: bool = True, add_chapter_title_page: bool = False) -> io.BytesIO:
        """
        Creates an EPUB file splitting the content into multiple chapter/volume files.
        """
        # 0. Clean Content (Remove Plan)
        content = self._remove_project_plan(content)
        content = self._clean_style_tags(content)
        # Clean title/project header from top of content
        content = self.clean_text_header(content, title)

        book = epub.EpubBook()
        book.epub_version = '2.0'
        book.set_identifier(f'{title}-{author}')
        book.set_title(title)
        book.set_language('ko')
        book.add_author(author)
        if publisher:
            book.add_metadata('DC', 'publisher', publisher)
        
        # CSS Style (사용자 지정 사양)
        style_content = """
        img { max-width:100%; max-height:100%; }
        p { font-family:굴림, sans-serif; font-style:normal; font-weight:normal; font-size:1em; margin-bottom:0.563em; padding:0em; line-height:170%; text-align:justify; text-indent:0.625em; }
        .center { text-align:center; }
        .bold { font-weight:bold; }
        .italic { font-style: italic; }
        h1 { font-family:굴림, sans-serif; font-style:normal; font-weight:bold; font-size:2em; margin:0em; padding:0em; text-align:center; }
        h2 { font-family:굴림, sans-serif; font-style:normal; font-weight:bold; font-size:1em; margin:0em; padding:0em; line-height:170%; text-align:center; text-indent:0.625em; }
        h3 { font-size:1em; font-weight:normal; margin-bottom:0.563em; text-indent:0; text-align:center; }
        """
        nav_css = epub.EpubItem(uid="style_nav", file_name="style/nav.css", media_type="text/css", content=style_content)
        book.add_item(nav_css)

        chapter_items = []
        
        # 1. Custom Cover Page
        cover_exists = False
        if cover_image_path and os.path.exists(cover_image_path):
            with open(cover_image_path, 'rb') as f:
                img_data = f.read()
            img = epub.EpubImage()
            img.file_name = 'cover.png'
            img.id = 'cover-img'
            img.content = img_data
            img.media_type = 'image/png'
            img.properties = ['cover-image']
            book.add_item(img)
            
            cover_html = epub.EpubHtml(title='Cover', file_name='cover.xhtml', lang='ko')
            cover_html.content = '<body><div style="text-align:center;"><img src="cover.png" alt="Cover"/></div></body>'
            cover_html.add_item(nav_css)
            book.add_item(cover_html)
            chapter_items.append(cover_html)
            cover_exists = True

        # 2. Custom Title Page
        import datetime
        current_year = datetime.date.today().year
        
        titlepage_html = epub.EpubHtml(title='Title Page', file_name='titlepage.xhtml', lang='ko')
        titlepage_content = f"""
        <body>
          <div style="text-align: center; margin-top: 5em;">
            <h1>{title}</h1>
            <p><br/><br/></p>
            <p>지은이 | {author}</p>
            {"<p>펴낸곳 | " + publisher + "</p>" if publisher else ""}
            <p>투고 및 문의 | sy@sybook.kr</p>
            <p><br/></p>
            <p>ⓒ{author}, {current_year}</p>
            <p><br/></p>
            <p style="font-size: 0.8em; color: #666666; line-height: 170%; max-width: 80%; margin: 0 auto; text-align: justify; text-indent: 0;">
              이 전자책은 대한민국 저작권법의 보호를 받는 저작물입니다. 출판권자로부터 서면에 의한 허락 없이 이 책의 일부나 전체를 어떠한 형태로도 재가공할 수 없습니다.
            </p>
          </div>
        </body>
        """
        titlepage_html.content = titlepage_content
        titlepage_html.add_item(nav_css)
        book.add_item(titlepage_html)
        chapter_items.append(titlepage_html)
        
        # Parse chapters
        # Look for [Chapter N] or ## N patterns
        parts = re.split(r'(?:^|\n)\[Chapter\s+(\d+)\]', content, flags=re.IGNORECASE)
        if len(parts) < 3:
            parts = re.split(r'(?:^|\n)##\s+(\d+)', content)
            
        toc_links = []
        
        # Build chapters dictionary
        chapters_dict = {}
        if len(parts) >= 3:
            for i in range(1, len(parts), 2):
                ch_num = int(parts[i])
                ch_body = parts[i+1].strip()
                if ch_body:
                    chapters_dict[ch_num] = ch_body

        if volumes and chapters_dict:
            # Group chapters by volumes -> 1 file per volume (e.g. chap_01.xhtml ~ chap_05.xhtml)
            for vol in volumes:
                vol_num = vol.get("volume_num") if isinstance(vol, dict) else getattr(vol, "volume_num", 1)
                start = vol.get("start_chap") if isinstance(vol, dict) else getattr(vol, "start_chap", 1)
                end = vol.get("end_chap") if isinstance(vol, dict) else getattr(vol, "end_chap", 1)
                vol_title = vol.get("title") if isinstance(vol, dict) else getattr(vol, "title", "제 장")
                
                vol_paragraphs = []
                for ch in range(start, end + 1):
                    if ch in chapters_dict:
                        ch_text = chapters_dict[ch]
                        # Extract title
                        first_line, _, rest = ch_text.partition('\n')
                        first_line = first_line.strip()
                        
                        parsed_title = self.clean_chapter_title_text(first_line)
                        if parsed_title and len(parsed_title) < 80:
                            ch_title = parsed_title
                            ch_body_clean = rest.strip()
                        else:
                            ch_title = f"제 {ch}화"
                            ch_body_clean = ch_text
                            
                        # 본문 제목 청소 (옵션)
                        if not show_chapter_title_in_body:
                            ch_body_clean = self._clean_chapter_title_from_body(ch_body_clean, ch_title)
                            
                        ch_body_html = self.format_body_paragraphs(ch_body_clean)
                        
                        # Add chapter title inline if requested
                        if show_chapter_title_in_body:
                            vol_paragraphs.append(f"<h3>{ch_title}</h3>\n{ch_body_html}")
                        else:
                            vol_paragraphs.append(ch_body_html)
                
                if vol_paragraphs:
                    ch_filename = f'chap_{vol_num:02d}.xhtml'
                    title_filename = f'chap_{vol_num:02d}_title.xhtml'
                    
                    target_link_file = ch_filename
                    
                    # 1. Volume 간지 페이지 추가
                    if add_chapter_title_page:
                        t_page = epub.EpubHtml(title=vol_title, file_name=title_filename, lang='ko')
                        t_page.content = f"""
                        <body>
                          <div style="text-align: center; margin-top: 8em; height: 100vh;">
                            <h2 style="font-size: 2em; font-weight: bold; text-align: center;">{vol_title}</h2>
                          </div>
                        </body>
                        """
                        t_page.add_item(nav_css)
                        book.add_item(t_page)
                        chapter_items.append(t_page)
                        target_link_file = title_filename
                        
                    # 2. Volume 본문 페이지 추가 (모든 소속 챕터 본문 합침)
                    c = epub.EpubHtml(title=vol_title, file_name=ch_filename, lang='ko')
                    
                    body_html = ""
                    if not add_chapter_title_page:
                        body_html = f"<h2>{vol_title}</h2>\n"
                        
                    body_html += "\n\n".join(vol_paragraphs)
                    c.content = f"<body>{body_html}</body>"
                    c.add_item(nav_css)
                    
                    book.add_item(c)
                    chapter_items.append(c)
                    
                    toc_links.append(epub.Link(target_link_file, vol_title, f'vol_{vol_num}'))
        else:
            # Simple fallback to single episode files
            if len(parts) < 3:
                body = content.strip()
                if body:
                    # Clean title from text start
                    body = self.clean_text_header(body, title)
                    
                    c = epub.EpubHtml(title='본문', file_name='chap_01.xhtml', lang='ko')
                    c.content = f'<body>{self.format_body_paragraphs(body)}</body>'
                    c.add_item(nav_css)
                    book.add_item(c)
                    chapter_items.append(c)
                    toc_links.append(epub.Link('chap_01.xhtml', '본문', 'chap_01'))
            else:
                for i in range(1, len(parts), 2):
                    ch_num = int(parts[i])
                    ch_body = parts[i+1].strip()
                    if not ch_body:
                        continue
                    
                    first_line, _, rest = ch_body.partition('\n')
                    first_line = first_line.strip()
                    
                    parsed_title = self.clean_chapter_title_text(first_line)
                    if parsed_title and len(parsed_title) < 80:
                        ch_title = parsed_title
                        ch_html_body = rest.strip()
                    else:
                        ch_title = f"제 {ch_num}화"
                        ch_html_body = ch_body
                        
                    # 본문 제목 청소 (옵션)
                    if not show_chapter_title_in_body:
                        ch_html_body = self._clean_chapter_title_from_body(ch_html_body, ch_title)
                    
                    ch_filename = f'chap_{ch_num:02d}.xhtml'
                    title_filename = f'chap_{ch_num:02d}_title.xhtml'
                    
                    target_link_file = ch_filename
                    
                    # 간지 페이지 추가 옵션
                    if add_chapter_title_page:
                        t_page = epub.EpubHtml(title=ch_title, file_name=title_filename, lang='ko')
                        t_page.content = f"""
                        <body>
                          <div style="text-align: center; margin-top: 8em; height: 100vh;">
                            <h2 style="font-size: 2em; font-weight: bold; text-align: center;">{ch_title}</h2>
                          </div>
                        </body>
                        """
                        t_page.add_item(nav_css)
                        book.add_item(t_page)
                        chapter_items.append(t_page)
                        target_link_file = title_filename
                        
                    c = epub.EpubHtml(title=ch_title, file_name=ch_filename, lang='ko')
                    
                    body_html = ""
                    if show_chapter_title_in_body and not add_chapter_title_page:
                        body_html = f"<h3>{ch_title}</h3>"
                        
                    body_html += self.format_body_paragraphs(ch_html_body)
                    c.content = f"<body>{body_html}</body>"
                    c.add_item(nav_css)
                    
                    book.add_item(c)
                    chapter_items.append(c)
                    
                    toc_links.append(epub.Link(target_link_file, ch_title, f'chap_{ch_num}'))
        
        # Set Table Of Contents
        book.toc = tuple(toc_links)
        
        # Add default NCX file
        book.add_item(epub.EpubNcx())
        
        # Spine: Exclude 'nav' to prevent nav.xhtml showing in the page list
        book.spine = chapter_items
        
        # Output to buffer
        buffer = io.BytesIO()
        epub.write_epub(buffer, book, {})
        buffer.seek(0)
        return buffer

    def create_serial_zip(self, episodes: list[str], title: str, author: str, publisher: str = None, format_type='txt', cover_image_path: str = None, show_chapter_title_in_body: bool = True, add_chapter_title_page: bool = False) -> io.BytesIO:
        """
        Creates a ZIP file containing split episodes.
        format_type: 'txt' or 'epub'
        """
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            for i, text in enumerate(episodes):
                filename = f"Episode_{i+1:03d}.{format_type}"
                
                if format_type == 'txt':
                    # If show_chapter_title_in_body is False, clean the chapter title line from the text episode
                    if not show_chapter_title_in_body:
                        first_line, _, rest = text.partition('\n')
                        first_line = first_line.strip()
                        parsed_title = self.clean_chapter_title_text(first_line)
                        if parsed_title and len(parsed_title) < 80:
                            cleaned_body = self._clean_chapter_title_from_body(rest.strip(), parsed_title)
                            text = cleaned_body
                        else:
                            text = self._clean_chapter_title_from_body(text, "")
                    zf.writestr(filename, text)
                elif format_type == 'epub':
                    # Create mini-epub for this episode
                    epub_buffer = self.create_epub(
                        f"{title} - Episode {i+1}", 
                        author, 
                        text, 
                        cover_image_path=cover_image_path, 
                        publisher=publisher,
                        show_chapter_title_in_body=show_chapter_title_in_body,
                        add_chapter_title_page=add_chapter_title_page
                    )
                    zf.writestr(filename, epub_buffer.getvalue())
                    
        zip_buffer.seek(0)
        return zip_buffer

export_service = ExportService()
