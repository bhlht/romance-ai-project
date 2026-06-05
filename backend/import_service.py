"""
Import Service for Publisher Hub
- Parses TXT and EPUB files
- Smart-splits text by chapter count or character count
- Ensures splits never break mid-sentence or mid-dialogue
"""

import re
import io
from ebooklib import epub
from typing import List, Dict, Any, Optional


class ImportService:
    """파일 가져오기 및 스마트 분할 서비스"""

    # ── File Parsing ──────────────────────────────────────────────

    def parse_txt(self, file_bytes: bytes) -> str:
        """TXT 파일에서 텍스트 추출"""
        # Try UTF-8 first, fallback to EUC-KR (common for Korean files)
        for encoding in ("utf-8-sig", "utf-8", "euc-kr", "cp949"):
            try:
                return file_bytes.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        # Last resort: lossy UTF-8
        return file_bytes.decode("utf-8", errors="replace")

    def parse_epub(self, file_bytes: bytes) -> str:
        """EPUB 파일에서 본문 텍스트 추출 (챕터 순서대로)"""
        buffer = io.BytesIO(file_bytes)
        book = epub.read_epub(buffer)

        texts: List[str] = []
        
        # 1. spine(독서 순서)에 따라 본문 추출
        if hasattr(book, 'spine') and book.spine:
            for item_ref in book.spine:
                idref = item_ref[0] if isinstance(item_ref, tuple) else item_ref
                item = book.get_item_with_id(idref)
                if item and item.get_type() == 9:  # ITEM_DOCUMENT (EpubHtml)
                    content = item.get_content()
                    if content:
                        text = self._html_to_text(content.decode("utf-8", errors="replace"))
                        if text.strip():
                            texts.append(text.strip())

        # 2. spine 정보가 없거나 텍스트를 추출하지 못한 경우 fallback (전체 ITEM_DOCUMENT)
        if not texts:
            for item in book.get_items_of_type(9):  # ITEM_DOCUMENT
                content = item.get_content()
                if content:
                    text = self._html_to_text(content.decode("utf-8", errors="replace"))
                    if text.strip():
                        texts.append(text.strip())

        return "\n\n".join(texts)

    def _html_to_text(self, html_str: str) -> str:
        """HTML 태그 제거, <p>/<br> → 줄바꿈 변환"""
        import html
        # head, style, script 태그 영역 자체를 제거하여 스타일 코드나 불필요한 메타텍스트 차단
        text = re.sub(r'<head\b[^>]*>([\s\S]*?)</head>', '', html_str, flags=re.IGNORECASE)
        text = re.sub(r'<style\b[^>]*>([\s\S]*?)</style>', '', text, flags=re.IGNORECASE)
        text = re.sub(r'<script\b[^>]*>([\s\S]*?)</script>', '', text, flags=re.IGNORECASE)

        # <br> 및 </p>, </div> 등을 개행문자로 치환
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'</p>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'</div>', '\n', text, flags=re.IGNORECASE)
        
        # 나머지 모든 HTML 태그 제거
        text = re.sub(r'<[^>]+>', '', text)
        
        # HTML 엔터티 디코딩 (&#13;, &nbsp; 등 처리)
        text = html.unescape(text)
        
        # Carriage Return 문자 제거 및 개행 문자 표준화
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        
        # 3개 이상의 개행문자를 2개(빈 줄 하나)로 축소
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()



    # ── Smart Split Engine ────────────────────────────────────────

    def smart_split(
        self,
        text: str,
        mode: str = "chapter",
        value: int = 10,
    ) -> List[str]:
        """
        스마트 분할 엔진

        Args:
            text: 원본 텍스트
            mode: "chapter" (회차 수 기준) 또는 "token" (글자 수 기준)
            value: chapter 모드면 총 회차 수, token 모드면 회차당 목표 글자 수

        Returns:
            분할된 에피소드 리스트

        분할 규칙:
        - 문장 끝(마침표, 느낌표, 물음표)에서만 분할
        - 따옴표("", '', 「」, 《》) 내부에서 분할 금지
        - 대화문 중간에서 분할 금지
        """
        if not text or not text.strip():
            return []

        text = text.strip()
        total_chars = len(text)

        if mode == "chapter":
            # 회차 수 기준: 정확하게 value 개의 에피소드로 균등 분산 분할
            if value <= 0:
                value = 1
            if value == 1:
                return [text]

            # 문장 경계 목록 생성
            boundaries = self._find_sentence_boundaries(text)
            num_boundaries = len(boundaries)

            if not boundaries or num_boundaries < value - 1:
                # 문장 경계가 없거나 회차 수보다 적으면 단순 글자 수 비례 강제 분할
                episodes = []
                chunk_len = total_chars // value
                for i in range(value):
                    start = i * chunk_len
                    end = (i + 1) * chunk_len if i < value - 1 else total_chars
                    episodes.append(text[start:end].strip())
                return [ep for ep in episodes if ep]

            chosen_boundaries = []
            last_boundary_idx = -1

            # 1부터 value - 1번째 분할선까지 위치 결정
            for i in range(1, value):
                target_pos = int(total_chars * i / value)
                
                # 남은 분할선들을 위해 최소 한 개씩의 문장 경계를 뒤에 남겨둠
                min_j = last_boundary_idx + 1
                max_j = num_boundaries - (value - i) - 1

                if min_j <= max_j:
                    best_j = min_j
                    best_diff = float('inf')
                    # target_pos에 가장 가까운 문장 경계 인덱스 찾기
                    for j in range(min_j, max_j + 1):
                        diff = abs(boundaries[j] - target_pos)
                        if diff < best_diff:
                            best_diff = diff
                            best_j = j
                    chosen_boundaries.append(boundaries[best_j])
                    last_boundary_idx = best_j
                else:
                    # 인덱스 범위 초과 예외 발생 시 비례적 강제 분할
                    last_val = boundaries[last_boundary_idx] if last_boundary_idx >= 0 else 0
                    forced_pos = last_val + (total_chars - last_val) // (value - i + 1)
                    chosen_boundaries.append(forced_pos)

            # 결정된 분할 지점들을 이용해 텍스트 조각 분리
            episodes = []
            split_points = [0] + chosen_boundaries + [total_chars]
            for idx in range(len(split_points) - 1):
                chunk = text[split_points[idx]:split_points[idx + 1]].strip()
                episodes.append(chunk if chunk else "...") # 빈 에피소드 방지
            return episodes


        else:
            # 글자 수 기준 분할 (기존 방식 유지)
            target_chars = value if value > 0 else 2000
            boundaries = self._find_sentence_boundaries(text)
            if not boundaries:
                return [text]

            episodes: List[str] = []
            current_start = 0

            while current_start < total_chars:
                target_end = current_start + target_chars

                if target_end >= total_chars:
                    remaining = text[current_start:].strip()
                    if remaining:
                        episodes.append(remaining)
                    break

                best_boundary = self._find_nearest_boundary(
                    boundaries, target_end, current_start
                )

                if best_boundary is None or best_boundary <= current_start:
                    best_boundary = target_end

                episode_text = text[current_start:best_boundary].strip()
                if episode_text:
                    episodes.append(episode_text)

                current_start = best_boundary
                while current_start < total_chars and text[current_start] in ('\n', '\r', ' '):
                    current_start += 1

            return episodes


    def _find_sentence_boundaries(self, text: str) -> List[int]:
        """
        문장 경계(분할 가능 위치) 인덱스 목록 반환.
        따옴표/대화문 내부의 마침표는 제외.
        """
        boundaries: List[int] = []
        in_quote = False
        quote_char = None
        i = 0
        length = len(text)

        # 한국어 따옴표 쌍 매핑 (Unicode escaped to avoid syntax issues)
        open_quotes = {
            '\u201c': '\u201d',  # " → "
            '\u2018': '\u2019',  # ' → '
            '\u300c': '\u300d',  # 「 → 」
            '\u300a': '\u300b',  # 《 → 》
            '"': '"',
            "'": "'",
        }
        close_quotes = set(open_quotes.values())

        while i < length:
            ch = text[i]

            # 따옴표 열기/닫기 추적
            if not in_quote and ch in open_quotes:
                in_quote = True
                quote_char = open_quotes[ch]
            elif in_quote and ch == quote_char:
                in_quote = False
                quote_char = None
                # 닫는 따옴표 다음이 문장 끝이면 경계로 추가
                if i + 1 < length and text[i + 1] in ('.', '!', '?', '。'):
                    boundaries.append(i + 2)
                elif i + 1 < length and text[i + 1] in ('\n', '\r'):
                    boundaries.append(i + 1)
                elif i + 1 >= length:
                    boundaries.append(i + 1)
            elif not in_quote:
                # 문장 종결 부호
                if ch in ('.', '!', '?', '。'):
                    # 다음 문자가 따옴표 닫기가 아닌지 확인
                    next_i = i + 1
                    while next_i < length and text[next_i] in (' ', '\t'):
                        next_i += 1
                    if next_i < length and text[next_i] not in close_quotes:
                        boundaries.append(next_i)
                    elif next_i >= length:
                        boundaries.append(next_i)
                # 빈 줄(문단 경계)도 분할 가능 위치
                elif ch == '\n' and i + 1 < length and text[i + 1] == '\n':
                    boundaries.append(i + 1)

            i += 1

        return sorted(set(boundaries))

    def _find_nearest_boundary(
        self,
        boundaries: List[int],
        target: int,
        min_pos: int,
    ) -> Optional[int]:
        """
        target에 가장 가까운 문장 경계를 찾되,
        min_pos 이후의 경계만 고려.
        target ± 20% 범위 내에서 검색.
        """
        search_range = max(500, int(target * 0.2))
        lower = max(min_pos + 100, target - search_range)  # 최소 100자 이상 진행
        upper = target + search_range

        # 범위 내 경계 필터링
        candidates = [b for b in boundaries if lower <= b <= upper]

        if not candidates:
            # 범위를 넓혀서 재검색
            candidates = [b for b in boundaries if b > min_pos + 50]
            if not candidates:
                return None
            # target에 가장 가까운 것 선택
            return min(candidates, key=lambda b: abs(b - target))

        # target에 가장 가까운 후보 선택 (약간 뒤쪽 우선)
        return min(candidates, key=lambda b: abs(b - target))

    # ── Metadata ──────────────────────────────────────────────────

    def get_split_metadata(self, episodes: List[str]) -> Dict[str, Any]:
        """분할 결과 메타데이터 반환"""
        char_counts = [len(ep) for ep in episodes]
        return {
            "total_episodes": len(episodes),
            "total_chars": sum(char_counts),
            "char_counts": char_counts,
            "avg_chars": sum(char_counts) // len(episodes) if episodes else 0,
            "min_chars": min(char_counts) if char_counts else 0,
            "max_chars": max(char_counts) if char_counts else 0,
        }

    def adjust_split(
        self,
        text: str,
        split_positions: List[int],
    ) -> List[str]:
        """
        수동으로 분할 위치를 지정하여 재분할.
        split_positions: 텍스트 내 분할 지점 인덱스 리스트 (오름차순)
        """
        positions = sorted(set([0] + split_positions + [len(text)]))
        episodes = []
        for i in range(len(positions) - 1):
            ep = text[positions[i]:positions[i + 1]].strip()
            if ep:
                episodes.append(ep)
        return episodes


import_service = ImportService()
