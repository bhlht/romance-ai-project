import os
import asyncio
import logging
import re
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("db_service")

# Database configuration from environment variables
DB_HOST = os.getenv("PG_HOST") or os.getenv("DB_HOST") or "localhost"
DB_PORT = os.getenv("PG_PORT") or os.getenv("DB_PORT") or "5432"
DB_NAME = os.getenv("PG_DATABASE") or os.getenv("DB_NAME") or ""
DB_USER = os.getenv("PG_USER") or os.getenv("DB_USER") or ""
DB_PASSWORD = os.getenv("PG_PASSWORD") or os.getenv("DB_PASSWORD") or ""

USE_DB = all([DB_NAME, DB_USER, DB_PASSWORD])

class DatabaseService:
    def __init__(self):
        self.pool = None
        if USE_DB:
            logger.info("Database credentials found. Initializing PostgreSQL pool on startup.")
        else:
            logger.warning("Database configuration (PG_DATABASE, PG_USER, PG_PASSWORD) not complete. Running in MOCK RAG mode.")

    async def initialize(self):
        if not USE_DB:
            return
        
        try:
            import asyncpg
            ssl_mode = os.getenv("DB_SSL", "false").lower() == "true"
            ssl_context = None
            if ssl_mode:
                import ssl
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
                
            self.pool = await asyncpg.create_pool(
                host=DB_HOST,
                port=int(DB_PORT),
                database=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
                min_size=2,
                max_size=10,
                statement_cache_size=0,  # Required for Supabase transaction mode PgBouncer
                ssl=ssl_context
            )
            logger.info("Successfully established connection pool to PostgreSQL (statement_cache_size=0).")
        except Exception as e:
            logger.error(f"Failed to create PostgreSQL connection pool: {e}. Falling back to MOCK RAG mode.")
            self.pool = None

    async def get_categories(self) -> list:
        """
        Retrieves categories (cd_t, cd_tname) from ebook_t that actually
        have active embeddings stored in ebook_vector_chunks.
        """
        if not USE_DB or not self.pool:
            return [{"cd_t": 7, "cd_tname": "할리퀸 로맨스"}]
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT DISTINCT t.cd_t, t.cd_tname 
                    FROM ebook_t t
                    INNER JOIN ebook_series b ON b.publisher_id = t.cd_t
                    INNER JOIN ebook_vector_chunks c ON c.series_id = b.series_id
                    ORDER BY t.cd_tname
                    """
                )
                return [{"cd_t": r["cd_t"], "cd_tname": r["cd_tname"]} for r in rows]
        except Exception as e:
            logger.error(f"Failed to get RAG categories: {e}")
            return []

    async def get_series(self, category_id: int = None, series_id: int = None, search_query: str = None) -> list:
        """
        Retrieves series (series_id, display_title) from ebook_series that actually
        have active embeddings in ebook_vector_chunks.
        Can filter by:
        1. series_id: retrieves specific series by ID
        2. search_query: matches display_title via ILIKE (max 50)
        3. category_id: matches publisher_id
        """
        if not USE_DB or not self.pool:
            return [{"series_id": 2556, "display_title": "그대이기에"}]
        
        try:
            async with self.pool.acquire() as conn:
                # 1. 특정 도서 ID 개별 조회 (UI 로딩/보존 목적 - 조인 생략)
                if series_id is not None:
                    rows = await conn.fetch(
                        """
                        SELECT series_id, display_title 
                        FROM ebook_series 
                        WHERE series_id = $1
                        """,
                        series_id
                    )
                    return [{"series_id": r["series_id"], "display_title": r["display_title"]} for r in rows]
                
                # 2. 도서명 검색 쿼리 (실제 청크가 있는 도서만 조인 필터링)
                if search_query:
                    search_pattern = f"%{search_query}%"
                    if category_id is not None:
                        rows = await conn.fetch(
                            """
                            SELECT DISTINCT b.series_id, b.display_title 
                            FROM ebook_series b
                            INNER JOIN ebook_vector_chunks c ON c.series_id = b.series_id
                            WHERE b.publisher_id = $1 AND b.display_title ILIKE $2
                            ORDER BY b.display_title
                            LIMIT 50
                            """,
                            category_id, search_pattern
                        )
                    else:
                        rows = await conn.fetch(
                            """
                            SELECT DISTINCT b.series_id, b.display_title 
                            FROM ebook_series b
                            INNER JOIN ebook_vector_chunks c ON c.series_id = b.series_id
                            WHERE b.display_title ILIKE $1
                            ORDER BY b.display_title
                            LIMIT 50
                            """,
                            search_pattern
                        )
                    return [{"series_id": r["series_id"], "display_title": r["display_title"]} for r in rows]
                
                # 3. 특정 장르 카테고리 전체 조회 (실제 청크가 있는 도서만 조인 필터링)
                if category_id is not None:
                    rows = await conn.fetch(
                        """
                        SELECT DISTINCT b.series_id, b.display_title 
                        FROM ebook_series b
                        INNER JOIN ebook_vector_chunks c ON c.series_id = b.series_id
                        WHERE b.publisher_id = $1
                        ORDER BY b.display_title
                        """,
                        category_id
                    )
                    return [{"series_id": r["series_id"], "display_title": r["display_title"]} for r in rows]
                
                # 4. 조건이 아무것도 없으면 빈 배열 반환 (테이블 풀 스캔 방지)
                return []
        except Exception as e:
            logger.error(f"Failed to get RAG series list: {e}")
            return []

    async def get_rag_context(
        self, 
        project_name: str, 
        query_text: str, 
        category_id: int = None,
        series_id: int = None,
        keyword: str = None,
        limit: int = 5
    ) -> str:
        """
        Retrieves relevant text segments from ebook_vector_chunks using similarity search,
        filtering optionally by category_id, series_id, or custom keywords.
        """
        if not USE_DB or not self.pool:
            # Mock fallback response
            logger.info("RAG search: returning mock data since database is not configured.")
            cat_label = "할리퀸 로맨스" if category_id == 7 else "전체"
            book_label = "그대이기에" if series_id == 2556 else "전체"
            return (
                f"[RAG 검색 결과 (MOCK 참조)]\n"
                f"- 참조 카테고리: {cat_label} (ID: {category_id})\n"
                f"- 참조 도서: {book_label} (ID: {series_id})\n"
                f"- 특정 키워드 필터: '{keyword or '없음'}'\n"
                f"- 검색 쿼리: '{query_text}'\n"
                f"- 설정 정보: 이 소설은 '{cat_label}'의 문체 특징과 '{book_label}'의 캐릭터 대화 호흡을 벤치마킹하여 작성됩니다. "
                f"인물 간의 긴장감 속에서 감정선이 서서히 녹아내리는 묘사가 강점입니다.\n"
                f"- 관련 묘사 프리셋: 깊어지는 골목의 정적 속에서 그들의 시선이 교차할 때 미묘한 긴장이 흐른다."
            )

        try:
            async with self.pool.acquire() as conn:
                where_clauses = []
                params = []
                
                # Check table existence first
                table_exists = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name = 'ebook_vector_chunks')"
                )
                if not table_exists:
                    return "[RAG 안내: PostgreSQL에 'ebook_vector_chunks' 테이블이 존재하지 않습니다.]"
                
                # Apply Category/Genre filter (maps to publisher_id in ebook_series)
                if category_id is not None:
                    params.append(category_id)
                    where_clauses.append(f"b.publisher_id = ${len(params)}")
                    
                # Apply Series/Book filter
                if series_id is not None:
                    params.append(series_id)
                    where_clauses.append(f"a.series_id = ${len(params)}")
                    
                # Apply tag or chunk_text keyword filter
                if keyword:
                    params.append(f"%{keyword}%")
                    kw_idx = len(params)
                    where_clauses.append(f"(a.chunk_text ILIKE ${kw_idx} OR a.tag::text ILIKE ${kw_idx})")
                
                # Vector Search using embedding
                search_query = query_text or keyword or "로맨스"
                embedding = await self._generate_gemini_embedding(search_query)
                
                where_str = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
                
                if embedding:
                    params.append(str(embedding))
                    embed_idx = len(params)
                    params.append(limit)
                    limit_idx = len(params)
                    
                    query = f"""
                        SELECT a.chunk_text, b.display_title as series_title, a.chapter_title
                        FROM ebook_vector_chunks a
                        INNER JOIN ebook_series b ON a.series_id = b.series_id
                        {where_str}
                        ORDER BY a.embedding <=> ${embed_idx}::vector
                        LIMIT ${limit_idx}
                    """
                    rows = await conn.fetch(query, *params)
                    if rows:
                        results = []
                        for r in rows:
                            results.append(
                                f"[도서: {r['series_title']} | 챕터: {r['chapter_title']}]\n"
                                f"{r['chunk_text']}"
                            )
                        return "\n\n---\n\n".join(results)
                
                # Fallback to Text Search (if embedding generation failed or pgvector is missing)
                params.append(f"%{search_query}%")
                query_idx = len(params)
                where_clauses.append(f"(a.chunk_text ILIKE ${query_idx})")
                
                params.append(limit)
                limit_idx = len(params)
                
                query = f"""
                    SELECT a.chunk_text, b.display_title as series_title, a.chapter_title
                    FROM ebook_vector_chunks a
                    INNER JOIN ebook_series b ON a.series_id = b.series_id
                    {where_str}
                    LIMIT ${limit_idx}
                """
                rows = await conn.fetch(query, *[p for p in params if p is not limit] + [limit])
                if rows:
                    results = []
                    for r in rows:
                        results.append(
                            f"[도서: {r['series_title']} | 챕터: {r['chapter_title']}]\n"
                            f"{r['chunk_text']}"
                        )
                    return "\n\n---\n\n".join(results)
                else:
                    return f"[RAG 결과: 'ebook_vector_chunks' 테이블에서 '{search_query}'에 매칭되는 데이터를 찾지 못했습니다.]"
                    
        except Exception as e:
            logger.error(f"Error during RAG database query: {e}")
            return f"[RAG 검색 오류: {str(e)}]"

    async def _generate_gemini_embedding(self, text: str) -> list:
        try:
            import google.generativeai as genai
            # Use gemini-embedding-001 with output_dimensionality=768 to match Supabase pgvector column
            response = genai.embed_content(
                model="models/gemini-embedding-001",
                content=text,
                task_type="retrieval_query",
                output_dimensionality=768
            )
            return response['embedding']
        except Exception as e:
            logger.error(f"Failed to generate embedding via Gemini: {e}")
            return None

db_service = DatabaseService()
