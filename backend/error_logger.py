import os
import json
import traceback
from datetime import datetime
import uuid

# D:\myProject\streamlit\logs\errors 폴더를 기본 경로로 설정
LOGS_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "logs", "errors"))

def log_error(error_type: str, message: str, detail: str = None, context: dict = None) -> str:
    """
    오류 정보를 logs/errors/YYYY-MM-DD/HHMMSS_오류타입_UUID.json 파일로 상세하게 기록합니다.
    - error_type: 오류 성격 (예: 'Gemini_API', 'FastAPI_500', 'Streamlit_UI', 'Database')
    - message: 오류 핵심 요약 메시지
    - detail: traceback 또는 상세 에러 메시지 (생략 시 자동으로 sys.exc_info traceback을 캡처)
    - context: 호출 파라미터, 유저ID, 입력 데이터 등 분석에 필요한 모든 정보
    """
    try:
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H%M%S")
        unique_id = uuid.uuid4().hex[:6]
        
        # 날짜별 폴더 생성 (예: logs/errors/2026-06-09/)
        date_folder = os.path.join(LOGS_BASE_DIR, date_str)
        os.makedirs(date_folder, exist_ok=True)
        
        # 상세 traceback 캡처
        tb_str = detail
        if not tb_str:
            tb_str = traceback.format_exc()
            if "NoneType: None" in tb_str:
                tb_str = "No traceback captured (not within except block)."
        
        # 로그 파일 바디 구성
        log_payload = {
            "timestamp": now.isoformat(),
            "date": date_str,
            "time": now.strftime("%H:%M:%S"),
            "error_type": error_type,
            "message": message,
            "traceback": tb_str,
            "context": context or {}
        }
        
        # 안전한 파일명 생성 (특수문자 제거)
        safe_type = "".join([c if c.isalnum() else "_" for c in error_type])[:30]
        filename = f"{time_str}_{safe_type}_{unique_id}.json"
        filepath = os.path.join(date_folder, filename)
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(log_payload, f, ensure_ascii=False, indent=2)
            
        print(f"[ErrorLogger] 오류가 성공적으로 기록되었습니다: {filepath}")
        return filepath
    except Exception as e:
        print(f"[ErrorLogger] 오류 로그 저장 중 오류 발생: {e}")
        print(f"[원본 오류 백업] Type: {error_type}, Msg: {message}")
        return ""
