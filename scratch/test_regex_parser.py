import re

raw_text = """{
    "scores": {
        "consistency": 60,
        "grammar_flow": 75,
        "creativity": 80
    },
    "feedback": {
        "consistency": "일관성 테스트 피드백",
        "grammar_flow": "가독성 테스트 피드백",
        "creativity": "창의성 테스트 피드백"
    },
    "overall_critique": "종합 비평",
    "improvement_suggestions": [],
    "recommended_chapters": []
  }"""

def extract_review_via_regex(raw_text: str) -> dict:
    scores = {"consistency": 70, "grammar_flow": 70, "creativity": 70}
    feedback = {"consistency": "분석 완료", "grammar_flow": "분석 완료", "creativity": "분석 완료"}
    overall_critique = ""
    improvement_suggestions = []
    recommended_chapters = []
    
    for key in ["consistency", "grammar_flow", "creativity"]:
        match = re.search(r'"' + key + r'"\s*:\s*(\d+)', raw_text, re.IGNORECASE)
        if match:
            scores[key] = int(match.group(1))
            
    feedback_block_match = re.search(r'"feedback"\s*:\s*\{(.*?)\}', raw_text, re.DOTALL | re.IGNORECASE)
    if feedback_block_match:
        block = feedback_block_match.group(1)
        print("Block content:", repr(block))
        for key in ["consistency", "grammar_flow", "creativity"]:
            match = re.search(r'"' + key + r'"\s*:\s*"((?:[^"\\]|\\.)*)"', block, re.DOTALL | re.IGNORECASE)
            if match:
                feedback[key] = match.group(1).replace(r'\"', '"').replace(r'\n', '\n').strip()
            else:
                match_lax = re.search(r'"' + key + r'"\s*:\s*"((?:[^"\\]|\\.)*)', block, re.DOTALL | re.IGNORECASE)
                if match_lax:
                    feedback[key] = match_lax.group(1).replace(r'\"', '"').replace(r'\n', '\n').strip()
    else:
        print("Feedback block match failed!")
        for key in ["consistency", "grammar_flow", "creativity"]:
            match = re.search(r'"feedback_' + key + r'"\s*:\s*"((?:[^"\\]|\\.)*)"', raw_text, re.DOTALL | re.IGNORECASE)
            if match:
                feedback[key] = match.group(1).replace(r'\"', '"').replace(r'\n', '\n').strip()
                    
    match_crit = re.search(r'"overall_critique"\s*:\s*"((?:[^"\\]|\\.)*)"', raw_text, re.DOTALL | re.IGNORECASE)
    if match_crit:
        overall_critique = match_crit.group(1).replace(r'\"', '"').replace(r'\n', '\n').strip()
        
    return {
        "scores": scores,
        "feedback": feedback,
        "overall_critique": overall_critique
    }

print("Result:", extract_review_via_regex(raw_text))
