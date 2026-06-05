import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()

class GeminiService:
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            print("Warning: GEMINI_API_KEY not found in environment variables.")
        else:
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel('models/gemini-3-flash-preview')
            self.image_model = genai.GenerativeModel('models/nano-banana-pro-preview')
            
        # Load Trends
        self.trends = self.load_trends()

    def load_trends(self):
        try:
            import json
            with open("backend/trends.json", "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("trends", [])
        except Exception as e:
            print(f"Error loading trends: {e}")
            return []

    async def generate_starter_paragraph(self, chars: str, world: str, plot_summary: str, ch_focus: str, writer_memo: str, previous_context: str, model_name: str = 'models/gemini-3.1-pro-preview') -> str:
        if not self.api_key:
            return ""

        prompt = f"""
        당신은 대한민국 최고의 베스트셀러 로맨스 소설 작가입니다.
        아래 설정과 이전 줄거리를 바탕으로, 독자를 즉시 몰입시키는 **다음 장면의 첫 2~3 문장**만 창작하십시오.
        어떠한 설명, 메타 코멘터리, 요약 없이 오직 소설 본문만 출력하십시오. 영어는 절대 사용하지 마십시오.

        [소설 설정]
        주요 인물: {chars}
        세계관 및 배경: {world}
        이번 화 전개 목표: {ch_focus}
        플롯 요약: {plot_summary}
        작가 지시사항: {writer_memo}

        [이전 내용 — 바로 다음 장면을 이어서 창작하십시오]
        {previous_context}

        [창작 요구사항]
        1. **분량**: 정확히 2~3 문장 (100~200자). 딥시크 AI가 이어서 본문을 계속 써야 하므로 절대 완결하지 마십시오.
        2. **문체**: 감각적 묘사(시각/청각/촉각)와 긴장감으로 독자를 즉시 장면 안으로 끌어들이십시오.
        3. **마지막 문장**: 미완성 긴장감으로 끝내십시오. (다음 작가가 자연스럽게 이어 쓸 수 있게)
        4. 오직 소설 **본문 텍스트**만 바로 출력하십시오. (Output ONLY the story text in Korean)
        """
        
        try:
            return await self._call_gem_with_retry(prompt, model_name)
        except Exception as e:
            print(f"Error generating starter paragraph: {e}")
            return ""

    async def polish_deepseek_output(
        self,
        deepseek_text: str,
        chars: str,
        starter: str = "",
        model_name: str = 'models/gemini-3-flash-preview'
    ) -> str:
        """
        [상용화 고도화] DeepSeek Best-of-3 출력을 Gemini가 경량 교정합니다.
        - 이름 오염 수정 (은믹 → 은미)
        - 비논리적 문장 제거
        - 문장 흐름 자연스럽게 연결
        - 핵심 내용은 100% 유지 (재창작 아님)
        """
        if not self.api_key or not deepseek_text or len(deepseek_text) < 30:
            return deepseek_text

        try:
            prompt = f"""당신은 한국 로맨스 소설 전문 교정 편집자입니다.
아래 AI가 생성한 소설 본문을 **최소한으로 교정**하십시오.

[등장 인물 공식 이름 — 반드시 이 이름으로 교정]
{chars}

[교정 규칙 (매우 중요)]
1. 인물 이름이 잘못 쓰인 경우(은믹→은미, 만재→만세 등)만 수정하십시오.
2. 의미가 통하지 않는 문장(예: "키스하는 회색 눈이 보였다")은 부분 삭제하십시오.
3. 문장 연결이 어색한 경우만 자연스럽게 연결하십시오.
4. **내용 추가, 요약, 확장, 재창작은 절대 하지 마십시오.**
5. **[가장 중요] 원래 분량(글자 수)을 95% 이상 그대로 유지하십시오. 절대 줄이거나 요약하지 마십시오.**
6. 오직 교정된 소설 본문 텍스트만 출력하십시오. (설명, 메타 코멘터리 금지)

[교정할 텍스트]
{deepseek_text}

[교정 결과]:"""

            polished = await self._call_gem_with_retry(prompt, model_name)
            if polished and len(polished) > 30:
                print(f"✨ Gemini Polish 완료 ({len(deepseek_text)}자 → {len(polished)}자)")
                return polished.strip()
            return deepseek_text
        except Exception as e:
            print(f"Polish failed (non-critical): {e}")
            return deepseek_text

    async def generate_scene_beats(self, chars: str, world: str, ch_focus: str, plot_summary: str, previous_context: str, model_name: str = 'models/gemini-3.1-pro-preview') -> list:
        """
        [상용화 고도화: Writer's Room]
        DeepSeek이 한 번에 2000자를 쓸 수 없으므로(물리적 토큰 한계), 
        Gemini(기획자)가 이번 화의 목표를 4개의 세부 장면(Beat)으로 쪼개줍니다.
        예: ["골목길에 숨기", "건달들의 대화", "은미의 밀착", "위기 모면과 떨림"]
        """
        if not self.api_key:
            return []

        prompt = f"""당신은 베스트셀러 로맨스 소설의 수석 기획자입니다.
아래의 설정을 바탕으로, 이번 화에서 전개해야 할 내용(ch_focus)을
**자연스럽게 이어지는 4개의 세부 장면(Beat)**으로 쪼개어 기획하십시오.

[설정]
인물: {chars}
배경: {world}
이번 화 전개 목표: {ch_focus}
(참고 플롯: {plot_summary})

[직전 본문 (이 내용부터 자연스럽게 이어져야 함)]
{previous_context}

[요구사항]
- 이번 화 목표(ch_focus)를 절대 한 번에 소진하지 마십시오. 서서히 감정을 쌓아 올려야 합니다.
- 다음과 같은 4차선(4-Beat) 구조를 반드시 지키십시오:
  * Beat 1 (도입/발단): '직전 본문'에서 바로 이어지며, 사건의 시작이나 긴장감을 조성하는 행동 묘사 중심
  * Beat 2 (전개/위기): 사건이 구체화되며 주인공들의 갈등이나 위기, 물리적 움직임 묘사 중심
  * Beat 3 (절정): 이번 화 목표(ch_focus)의 핵심 감정선이 폭발하거나 스킨십/클라이맥스가 터지는 순간
  * Beat 4 (결말/여운): 폭풍이 지나간 후의 어색함, 떨림, 혹은 다음 화를 기대하게 만드는 작은 여운
- 각 Beat는 보조 작가가 500자 정도의 본문을 쓸 수 있도록 구체적인 '행동'과 '대사 방향', '상황 묘사'를 포함해야 합니다.
- 반드시 JSON 배열(Array of strings) 형태로만 출력하십시오. 백틱(`)이나 markdown 코드를 쓰지 마십시오.
예시: [
  "학원 밖으로 나선 두 사람 앞에 사기꾼 강사가 불량배들을 대동하고 나타나는 위기 상황 묘사",
  "만세가 정체를 숨긴 채 상황을 파악하는 사이, 은미가 그의 손목을 낚아채고 노량진 골목으로 정신없이 도망치는 긴박한 액션",
  "막다른 골목 틈새에 숨어 숨결이 닿을 듯 밀착한 두 사람. 거친 숨을 몰아쉬며 '내가 지켜줄게요'라고 속삭이는 은미와 당황한 만세의 심장박동 묘사",
  "불량배들의 발소리가 멀어지는 가운데, 이성으로 의식하지 않았던 은미의 순진한 눈빛에 처음으로 가슴이 요동치는 만세의 복잡한 감정선 마무리"
]

[결과 JSON]:"""

        try:
            # 강제로 JSON 출력만 하도록 프롬프트 설정
            result = await self._call_gem_with_retry(prompt, model_name)
            
            import json, re
            # 대괄호 [ ] 안의 내용만 정확하게 추출 (불필요한 텍스트 쓰레기 제거)
            match = re.search(r'\[.*\]', result, re.DOTALL)
            if match:
                cleaned = match.group(0)
                beats = json.loads(cleaned)
                if isinstance(beats, list) and len(beats) > 0:
                    return beats[:4]
            return [ch_focus]
        except Exception as e:
            print(f"Beat generation failed: {e}")
    async def generate_next_prompts(self, chapter_num: int, chapter_outline: str, recent_memory: str, model_name: str = 'models/gemini-3-flash-preview') -> dict:
        """
        [상용화 고도화] 
        다음 전개 방향 제안을 빠르고 안정적인 Gemini를 이용해 생성.
        """
        if not self.api_key:
            return {
                "A안 (감정/갈등 집중)": f"[제{chapter_num}화 전개] 서로의 오해가 깊어지며 감정이 격돌하는 방향으로 전개해 줘.",
                "B안 (사건/위기 발생)": f"[제{chapter_num}화 전개] 뜻밖의 사건이 터지며 분위기가 반전되는 방향으로 전개해 줘.",
                "C안 (관계 진전/스킨십)": f"[제{chapter_num}화 전개] 어색했던 거리가 좁혀지며 텐션이 높아지는 방향으로 전개해 줘."
            }

        prompt = f"""당신은 베스트셀러 로맨스 소설 작가의 든든한 보조 작가입니다.
현재 작성 중인 [회차: 제{chapter_num}화]의 플롯 아웃라인과 지금까지의 요약(Memory)을 바탕으로,
해당 회차에서 **어떤 사건과 감정선이 벌어질지 구체적으로 묘사하는 3~5문장 길이의 상세한 '전개 줄거리 요약본'** 3가지를 제안하십시오.

단순한 한 줄 지시문이 아니라, 이 회차 안에서 인물들이 구체적으로 어떤 행동을 하고 어떤 대화나 감정을 나눌지 상세히 풀어써야 합니다.

[이전 요약]
{recent_memory}

[제{chapter_num}화 플롯 아웃라인]
{chapter_outline}

[요구사항]
- A안: 인물들 간의 오해, 질투, 혹은 내면의 상처가 터져 나오는 감정적인 갈등을 중심으로 한 구체적인 요약
- B안: 로맨스의 흐름을 바꾸는 통제할 수 없는 외부 사건이나 뜻밖의 돌발 상황을 중심으로 한 구체적인 요약
- C안: 물리적, 심리적 거리가 급격히 좁혀지며 로맨틱하고 아슬아슬한 텐션이 폭발하는 상황을 중심으로 한 구체적인 요약
- 각 안은 반드시 3~5문장의 구체적인 줄거리 형태로 작성하십시오.
- 출력은 반드시 아래 JSON 형식을 정확히 지키십시오. 절대 다른 말은 덧붙이지 마십시오.

{{
    "A안 (감정/갈등 집중)": "[제{chapter_num}화 상세 요약] ...",
    "B안 (사건/위기 발생)": "[제{chapter_num}화 상세 요약] ...",
    "C안 (관계 진전/스킨십)": "[제{chapter_num}화 상세 요약] ..."
}}
"""
        try:
            result = await self._call_gem_with_retry(prompt, model_name)
            
            import json, re
            match = re.search(r'\{.*\}', result, re.DOTALL)
            if match:
                cleaned = match.group(0)
                result_json = json.loads(cleaned)
                if isinstance(result_json, dict) and "A안 (감정/갈등 집중)" in result_json:
                    return result_json
        except Exception as e:
            print(f"Next prompt generation failed: {e}")
            
        return {
            "A안 (감정/갈등 집중)": f"[제{chapter_num}화 상세 요약] 두 사람 사이의 묵혀둔 오해가 작은 계기로 터져 나오며 격렬한 말다툼이 벌어집니다. 상처받은 눈빛 속에서도 서로를 향한 갈망을 숨기지 못하는 감정선이 핵심입니다.",
            "B안 (사건/위기 발생)": f"[제{chapter_num}화 상세 요약] 평화로운 일상 도중 예상치 못한 불청객이나 외부의 사건이 터집니다. 위기를 넘기기 위해 두 사람이 어쩔 수 없이 힘을 합치며 분위기가 급반전됩니다.",
            "C안 (관계 진전/스킨십)": f"[제{chapter_num}화 상세 요약] 우연한 스킨십이나 좁은 공간에 갇히는 상황이 발생하여 묘한 기류가 흐릅니다. 평소와 다른 상대방의 숨결과 시선을 의식하며 아슬아슬한 텐션이 폭발합니다."
        }

    async def generate_v3_draft(
        self, 
        prompt: str, 
        chars: str, 
        world: str, 
        plot_summary: str, 
        ch_focus: str, 
        style_directions: str,
        previous_context: str, 
        model_name: str = 'models/gemini-3.1-pro-preview',
        temperature: float = 0.7
    ) -> str:
        """
        [V3 아키텍처: Gemini 메인 작가]
        제미나이가 전체 서사와 개연성을 책임지고 2000자 분량의 초안을 작성합니다.
        가장 중요한 역할: 감정선이 폭발하거나 관능/오감 묘사가 필요한 문장을 
        <STYLE>...</STYLE> 태그로 감싸서, 백엔드가 딥시크에게 해당 문장만 윤문을 맡길 수 있게 합니다.
        """
        if not self.api_key:
            return ""

        sys_prompt = f"""당신은 대한민국 최고의 베스트셀러 로맨스 소설 메인 작가입니다. 
아래의 설정을 바탕으로, 직전 내용에서 감정선과 시간/공간적 흐름이 물 흐르듯 자연스럽게 이어지는 이번 화 본문(약 2,000자)을 작성하십시오.

[설정 정보]
인물: {chars}
배경: {world}
참고 플롯 아웃라인: {plot_summary}

[시간/공간적 전개 정보 (흐름 추적)]
{previous_context}

이번 화 전개 목표: {ch_focus}

[문체 및 분위기 지시사항]
{style_directions}

[사용자 직접 지시사항]
{prompt}

[작성 규칙 (매우 중요)]
1. 기-승-전-결의 서사를 완벽하게 짜서, 중간에 상황이나 감정을 생략하고 건너뛰지 말고 2000자(공백 포함) 분량으로 길고 상세히 작성하십시오.
2. 이야기의 흐름, 행동의 개연성, 인물 간의 대화를 자연스럽고 타당하게 이끌어가십시오.
3. **[개연성 및 브릿지(Bridge) 작성 핵심 지침]**:
   - 직전 화의 마무리에 나타난 사건/공간과 이번 화 전개 목표 사이에 상당한 시간적/공간적 변화가 있거나(예: 우연한 마주침 후 바로 같이 일함 등), 감정의 격차가 존재한다면, 소설 전반부(초반 몇 문단)에 이를 **현실적으로 설득력 있게 메워주는 개연성 있는 전환 징검다리(설명, 회상 대화, 혹은 중간 계기 서술)**를 반드시 삽입하십시오.
   - 갑자기 뜬금없이 변화된 결론에서 시작하지 말고, 독자가 상황 변화를 자연스럽게 납득할 수 있게 인지적 흐름을 구축하십시오.
4. **[핵심 지시] 감정선이 폭발하는 장면, 숨결이나 텐션이 느껴지는 신체 접촉, 심장박동 등의 하이라이트 문장이 나올 때마다, 해당 문장(순수 텍스트) 앞뒤를 반드시 `<STYLE>`과 `</STYLE>` 태그로 감싸십시오.**
   - 예시: 은미가 그의 손목을 낚아채며 뛰었다. <STYLE>거친 숨결이 닿을 듯 밀착한 그녀의 눈빛에 만세의 이성이 아득해졌다.</STYLE> 만세는 어찌할 바를 몰랐다.
5. 절대 태그 안에 대화문(" ")을 통째로 넣지 마십시오. 대화는 지문에만 태그를 거십시오.
   - 나쁜 예: <STYLE>"내가지켜줄게요." 그녀가 말했다.</STYLE>
   - 좋은 예: "내가 지켜줄게요." <STYLE>그녀의 결연한 속삭임이 귓가를 간지럽히자 심장이 터질 듯 요동쳤다.</STYLE>
6. 전체 본문 안에 `<STYLE>` 태그 블록을 최소 4개에서 8개 정도 적절히 배치하십시오.
7. **[표절 및 모방 방지 규칙]**: `[참고 데이터 (RAG 검색 결과)]`에 포함된 소설 원고의 문체, 비유법, 감정 묘사의 특징은 적극적으로 벤치마킹하되, **절대 문장이나 대사를 그대로 베껴 쓰지 마십시오.** 현재 설정된 인물과 이번 화 전개 목표에 맞게 완전히 새로운 독창적인 문장으로 재구성(Paraphrase)하여 집필하십시오.

오직 소설 본문 결과물만 출력하십시오.
"""

        try:
            result = await self._call_gem_with_retry(sys_prompt, model_name, temperature=temperature)
            return result.strip()
        except Exception as e:
            print(f"V3 Draft generation failed: {e}")
            return f"Error interacting with Gemini API: {str(e)}"
    async def analyze_text(self, text: str, model_name: str = 'models/gemini-3.1-pro-preview') -> str:
        if not self.api_key:
            return "Error: Gemini API Key is missing. Please configure the server."

        prompt = f"""
        당신은 대한민국 최고의 로맨스 소설 전문 편집자입니다. 
        다음 텍스트를 분석하여 작가에게 도움이 되는 전문적인 피드백을 제공하십시오.
        
        [분석 항목]
        1. 설정 충돌이나 서사의 개연성 점검.
        2. 캐릭터의 감정선 및 행동 동기의 타당성 분석.
        3. 로맨틱한 분위기를 극대화하기 위한 문체 및 표현 제안.
        
        [분석할 텍스트]
        {text}
        
        [지시사항]
        분석 결과를 구조화된 형식으로 제공하십시오. 
        반드시 전적으로 한국어로만 답변하십시오. 영어는 일절 사용하지 마십시오. (Output ONLY in Korean)
        """
        
        try:
            return await self._call_gem_with_retry(prompt, model_name)
        except Exception as e:
            return f"Error interacting with Gemini API: {str(e)}"

    async def analyze_novel_content(self, text: str) -> dict:
        """
        Analyzes a novel text to extract metadata.
        Target Output: JSON with genre, keywords, mood, summary.
        """
        if not self.api_key:
            return {"error": "Gemini API Key missing"}

        # Truncate text if too long to save cost/time (optional, can be adjusted)
        # Using first 30,000 characters is usually enough for style/intro, 
        # but for full summary, we might need more. 
        # Gemini 1.5 Flash is recommended for full context. 
        # Truncating to 1,000,000 characters (approx 200k-300k tokens).
        # Gemini 1.5 Flash supports up to 1M tokens, so this is safe and allows full summary.
        
        prompt = f"""
        Analyze the following novel content/excerpt and provide a JSON response.
        Do not include markdown formatting like ```json ... ```, just the raw JSON.
        
        Required JSON Structure:
        {{
            "genre": "Specific Sub-genre",
            "keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"],
            "mood": "Overall atmosphere (e.g., Melancholic, Cheerful, Tense)",
            "summary": "A concise plot summary (3-5 sentences)."
        }}

        Novel Content:
        {text[:1000000]} 
        """
        # Truncating to 1M chars to prevent extreme edge cases/memory issues, 
        # but this covers almost all standard romance novels.
        
        try:
            raw_text = await self._call_gem_with_retry(prompt, 'gemini-3.1-flash')
            # Simple cleanup to ensure valid JSON
            import json
            cleaned_text = raw_text.replace("```json", "").replace("```", "").strip()
            return json.loads(cleaned_text)
        except Exception as e:
            return {"error": f"Analysis failed: {str(e)}", "raw_response": str(e)}

    async def generate_cover_prompt(self, text, model_name: str = 'gemini-3.1-flash'):
        prompt = f"""
        Based on the following romance story, write a detailed, high-quality image generation prompt suitable for AI art tools like Midjourney, DALL-E 3, or Stable Diffusion.
        
        Focus on:
        - Main characters (appearance, clothing)
        - Setting (background, lighting, atmosphere)
        - Artistic style (e.g., Oil painting, Digital Art, Watercolor, Cinematic lighting)
        - Color palette
        
        The output should be a single string in English, ready to be pasted into an image generator.
        Format: "An exquisite digital art cover of... [details] ... --ar 2:3"

        Story Context:
        {text[:5000]}
        """
        try:
            return await self._call_gem_with_retry(prompt, model_name)
        except Exception as e:
            return f"Error generating prompt: {str(e)}"

    async def generate_story_idea(self, genre="Random", spice_level="19금(없음)", model_name="models/gemini-3-flash-preview", apply_trends=True, moods=None, male_tags=None, female_tags=None, arc="", char_sheet="", world_setting=""):
        """
        Generates a creative romance story premise based on genre, spice, and existing bible.
        """
        
        # Format trends for the prompt
        trend_context = ""
        if apply_trends and self.trends:
            trend_list = [f"- {t['name']}: {t['description']}" for t in self.trends]
            trend_context = "\n**Popular K-Romance Trends (Use ONLY if they enhance the user's selected tags):**\n" + "\n".join(trend_list)

        # Context from Bible
        bible_context = ""
        if char_sheet:
            bible_context += f"\n[EXISTING CHARACTERS]\n{char_sheet}\n"
        if world_setting:
            bible_context += f"\n[WORLD SETTING]\n{world_setting}\n"

        # User Preferences
        mood_str = ', '.join(moods) if moods else '미정'
        male_str = ', '.join(male_tags) if male_tags else '미정'
        female_str = ', '.join(female_tags) if female_tags else '미정'

        prompt = f"""
        당신은 대한민국 최고의 웹소설 기획자이자 로맨스 작가입니다. 
        작가님이 새로운 로맨스 소설을 시작하려고 합니다. 다음의 키워드와 설정을 바탕으로, 독자의 마음을 사로잡을 수 있는 매혹적인 소설 아이디어를 생성하십시오.

        [설정 정보]
        - 장르: {genre}
        - 수위: {spice_level}
        - 분위기(Mood): {mood_str}
        - 남주인공 태그: {male_str}
        - 여주인공 태그: {female_str}
        - 핵심 서사 구조: {arc}
        {trend_context}
        
        [참고 데이터]
        - 기존 인물 설정: {char_sheet if char_sheet else "없음"}
        - 기존 세계관 설정: {world_setting if world_setting else "없음"}

        [지시사항]
        1. **제목**: 소설의 분위기와 장르를 잘 드러내는 감각적인 제목 3가지를 제안하십시오.
        2. **로그라인**: 이야기의 핵심을 1~2문장으로 요약하십시오.
        3. **줄거리 요약**: 주인공들의 첫 만남과 핵심 갈등, 그리고 로맨틱한 절정 부분을 포함하여 3~5문단으로 설명하십시오.
        
        중요: 반드시 전적으로 한국어로만 답변하십시오. 영어는 일절 사용하지 마십시오. (Output ONLY in Korean)
        """
        try:
            return await self._call_gem_with_retry(prompt, model_name)
        except Exception as e:
            return f"Error generating story idea: {str(e)}"

    async def _call_gem_with_retry(
        self, 
        prompt: str, 
        model_name: str, 
        max_tokens: int = 8192, 
        retries: int = 2,
        temperature: float = None
    ) -> str:
        """
        Helper to call Gemini with retries and fallback to Flash.
        """
        import asyncio
        import time
        
        current_model = model_name
        if "RAG" in current_model or "PostgreSQL" in current_model:
            current_model = "gemini-2.5-flash"
        if not current_model.startswith("models/"):
            current_model = f"models/{current_model}"
            
        for attempt in range(retries + 1):
            try:
                gen_config = {"max_output_tokens": max_tokens}
                if temperature is not None:
                    gen_config["temperature"] = temperature
                
                model = genai.GenerativeModel(current_model)
                response = await model.generate_content_async(
                    prompt, 
                    generation_config=gen_config,
                    request_options={"timeout": 60}
                )
                if response and response.text:
                    return response.text.strip()
                raise Exception("Empty response from AI")
            except Exception as e:
                err_str = str(e)
                print(f"--- Gemini Attempt {attempt+1} Failed ({current_model}): {err_str} ---")
                
                # Check for specific quota or internal errors
                if attempt < retries:
                    # Exponential backoff
                    wait_time = (attempt + 1) * 2
                    await asyncio.sleep(wait_time)
                    
                    # If it's a 500/504 or internal error on a 'Pro' model, try falling back to Flash
                    if ("504" in err_str or "500" in err_str or "Cancelled" in err_str) and "pro" in current_model.lower():
                        current_model = "models/gemini-3-flash-preview"
                        print(f"--- Falling back to {current_model} for next attempt ---")
                    continue
                else:
                    raise e

    async def generate_next_scene_choices(self, story_context: str, chapter_focus: str, chars: str, rel_map: str, model_name="models/gemini-3-flash-preview") -> list:
        """
        Analyzes the current story state and suggests 3 creative next directions.
        """
        prompt = f"""
        당신은 대한민국 최고의 베스트셀러 로맨스 소설 작가이자 창작 디렉터입니다.
        작가가 다음 장면의 전개를 고민하고 있습니다. 가장 매력적이고 독자의 심금을 울리는 3가지 창의적인 전개 방향을 제시해 주세요.
        
        [현재의 줄거리 (최신 2000자)]
        {story_context[-2000:]}
        
        [현재 회차의 최종 목표]
        {chapter_focus}
        
        [등장인물 정보]
        {chars}
        
        [인물 관계도]
        {rel_map}
        
        [지시사항]
        다음 장면에 대한 3가지의 다양하고 강렬한 선택지(A, B, C 옵션)를 제공하십시오.
        각 선택지는 반드시:
        1. [현재의 줄거리]의 마지막 문장에서 자연스럽게 이어져야 합니다.
        2. [현재 회차의 최종 목표]를 향해 서사를 진전시켜야 합니다.
        3. 설정된 [인물 관계도]와 캐릭터의 성격을 철저히 준수하십시오.
        4. 서로 다른 분위기를 가져야 합니다 (예: 옵션 A는 내면적 감정, 옵션 B는 고조되는 갈등, 옵션 C는 설레는 로맨틱한 순간).
        
        [응답 형식]
        반드시 다음 형식을 지켜 3개 문단으로 답변하십시오. 영어는 절대 사용하지 마십시오.
        옵션 A: [전개 내용...]
        옵션 B: [전개 내용...]
        옵션 C: [전개 내용...]
        
        중요: 반드시 전적으로 한국어로만 작성하십시오. 비평이나 코멘트는 생략하고 오직 이야기의 전개 방향만 제시하십시오. (Output ONLY in Korean)
        """
        try:
            res_text = await self._call_gem_with_retry(prompt, model_name)
            # Parse the options
            import re
            options = re.findall(r"옵션 [ABC]:\s*(.*)", res_text)
            if not options:
                # Fallback to English marker if the model occasionally sticks to it, or check for "Option"
                options = re.findall(r"(?:옵션|Option) [ABC]:\s*(.*)", res_text)
            
            if not options:
                # Fallback split
                options = [opt.strip() for opt in res_text.split("\n\n") if opt.strip()][:3]
            return options
        except Exception as e:
            return [f"Error generating choices: {str(e)}"]

    async def generate_plot(self, settings: dict, model_name="models/gemini-3-flash-preview") -> str:
        """
        Generates a structured plot outline based on provided settings.
        """
        idea_context = ""
        if settings.get('idea_premise'):
            idea_context = f"\n[핵심 스토리 아이디어]\n{settings.get('idea_premise')}\n"
            
        style_context = ""
        if settings.get('style'):
            style_context = f"\n[문체 및 분위기 강제 적용]\n- 문체: {settings.get('style')}\n- 페르소나: {settings.get('persona', '')}\n- 유머 레벨: {settings.get('humor_level', '0')}/10\n(주의: 위 문체와 유머 레벨을 플롯(줄거리) 전개 방식과 사건 구성에 적극적으로 반영할 것!)\n"

        prompt = f"""
        당신은 대한민국 최고의 베스트셀러 로맨스 소설 작가이자 기획자입니다.
        다음 설정을 바탕으로, 독자를 사로잡을 수 있는 정교한 50회분 소설 줄거리(플롯)를 기획하십시오.
        {idea_context}{style_context}
        [스토리 기본 설정]
        - 장르: {settings.get('genre', 'Romance')}
        - 수위: {settings.get('spice', 'Unknown')}
        - 분위기: {settings.get('mood', 'Unknown')}
        - 인물: {settings.get('chars', 'Unknown')}
        - 세계관/배경: {settings.get('world', 'Unknown')}
        - 핵심 테마: {settings.get('arc', 'Unknown')}
        - 트렌드 반영: {settings.get('trends', 'None')}

        [지시사항]
        기승전결(4단 구성)에 따라 정확히 **50회차 분량의 줄거리**를 생성하십시오.
        
        **중요**: 반드시 위에서 제공된 캐릭터와 세계관 설정을 유지하십시오. 
        각 회차는 명확한 제목과 함께 해당 회차의 핵심 전개를 담은 2-3줄의 요약을 포함해야 합니다.
        
        **회차 구성 가이드 (반드시 준수)**:
        - 제1부 (기: 도입부): 1~10화
        - 제2부 (승: 전개): 11~25화
        - 제3부 (전: 위기/절정): 26~40화
        - 제4부 (결: 결말): 41~50화
        
        중요: 반드시 전 50회차를 모두 생성하십시오. 도중에 멈추지 마십시오.
        어떠한 경우에도 한국어로만 답변하십시오. 영어는 일절 사용하지 마십시오. (Output ONLY in Korean)
        """
        try:
            return await self._call_gem_with_retry(prompt, model_name)
        except Exception as e:
            return f"Plot Generation Error: {str(e)}"

    async def generate_full_outline(self, settings: dict, total_chapters=50, model_name="models/gemini-3.1-pro-preview", reference_outline: str = ""):
        """
        Generates a 50-chapter outline in JSON format.
        """
        base_instruction = ""
        if reference_outline:
            base_instruction = f"""
            [기존 줄거리 정보]
            {reference_outline}

            [지시사항]
            위의 [기존 줄거리 정보]를 바탕으로 정확히 {total_chapters}회차 분량으로 내용을 확장하고 구조화하십시오.
            - 원래의 플롯 흐름과 감정선을 유지하십시오.
            - 기존 내용을 촘촘하게 나누어 구체적인 회차별 줄거리를 만드십시오.
            - 만약 기존 내용이 짧다면, 창의적이고 개연성 있는 에피소드를 추가하여 {total_chapters}회차를 채우십시오.
            """
        else:
            base_instruction = f"""
            아래의 설정을 바탕으로 새로운 {total_chapters}회차 분량의 독창적인 소설 줄거리를 생성하십시오.
            """

        prompt = f"""
        당신은 대한민국 최고의 웹소설 전문 기획자이자 작가입니다.
        
        {base_instruction}

        [소설 설정]
        - 장르: {settings.get('genre', 'Romance')}
        - 테마: {settings.get('theme', 'Love')}
        - 주요 인물: {settings.get('characters', 'Unknown')}
        - 핵심 갈등: {settings.get('conflict', 'Standard')}

        [구조: 기승전결 (4단계 구성)]
        - 제1부 (도입): 약 1~{int(total_chapters * 0.2)}화
        - 제2부 (전개): 약 {int(total_chapters * 0.2) + 1}~{int(total_chapters * 0.5)}화
        - 제3부 (위기/절정): 약 {int(total_chapters * 0.5) + 1}~{int(total_chapters * 0.8)}화
        - 제4부 (결말): 약 {int(total_chapters * 0.8) + 1}~{total_chapters}화

        [출력 형식 (JSON)]
        {{
            "title": "소설 제목",
            "chapters": [
                {{
                    "chapter_num": 1,
                    "title": "회차 제목",
                    "summary": "상세한 줄거리 (3~4문장)",
                    "key_events": ["핵심 사건 1", "핵심 사건 2"]
                }},
                ... ({total_chapters}화까지)
            ]
        }}

        중요: 반드시 유효한 JSON 형식으로 출력하십시오. 한국어로 작성하십시오.
        어떠한 경우에도 영어 설명이나 인사말 없이 오직 JSON 객체만 반환하십시오.
        """
        try:
            # High token limit needed for 50 ch outline
            raw_text = await self._call_gem_with_retry(prompt, model_name, max_tokens=8192)
            cleaned = raw_text.replace("```json", "").replace("```", "").strip()
            import json
            return json.loads(cleaned)
        except Exception as e:
            return {"error": f"Outline generation failed: {str(e)}"}

    def _parse_outline_to_json(self, text, total_chapters):
        """
        Parses the text outline into a structure for the batch generator.
        Expected format:
        ## 1. Part Title
        - Chapter 1: Title ...
        """
        chapters = []
        current_part = ""
        import re
        
        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            if not line: continue
            
            # Match Part
            if line.startswith("##"):
                current_part = line.replace("##", "").strip()
            
            # Match Chapter
            # Regex to match "- Chapter 1: Title" or "Chapter 1: Title"
            match = re.search(r'(?:-\s*)?Chapter\s*(\d+)\s*[:.]\s*(.+)', line, re.IGNORECASE)
            if match:
                ch_num = int(match.group(1))
                content = match.group(2)
                
                # Split title and summary if possible
                title = content
                summary = content
                
                # Check for "Summary" or parenthesis
                if "(" in content:
                    parts = content.split("(", 1)
                    title = parts[0].strip()
                    summary = parts[1].strip().rstrip(")")
                
                chapters.append({
                    "chapter_num": ch_num,
                    "title": title,
                    "summary": f"[{current_part}] {summary}",
                    "key_events": [summary] # Simple default
                })
        
        # Fallback if parsing failed
        if not chapters:
            return {"error": "Failed to parse outline. Raw text: " + text[:500]}
            
        return {"chapters": chapters}

    async def generate_marketing_data(self, text, model_name="models/gemini-3-flash-preview"):
        prompt = f"""
        당신은 대한민국 최고의 소설 마케팅 전문가이자 작가입니다.
        다음 소설 내용을 분석하여 독자의 시선을 사로잡을 수 있는 마케팅 패키지를 JSON 형식으로 생성하십시오.
        
        [필수 JSON 구조]
        {{
            "titles": ["매력적인 제목 1", "매력적인 제목 2", "매력적인 제목 3", "매력적인 제목 4", "매력적인 제목 5"],
            "blurb": "독자의 궁금증을 유발하는 강렬한 소개/책 초문 (문단 형태)",
            "summary": "간결하고 명확한 줄거리 요약 (3~5문장)",
            "keywords": ["키워드1", "키워드2", "키워드3", "키워드4", "키워드5"]
        }}

        [소설 내용]
        {text[:10000]}

        [지시사항]
        중요: 모든 출력값은 반드시 한국어로 작성하십시오. 영어 설명이나 인사말 없이 오직 순수한 JSON 객체만 반환하십시오.
        """
        try:
            raw_text = await self._call_gem_with_retry(prompt, model_name)
            # Cleanup JSON
            cleaned = raw_text.replace("```json", "").replace("```", "").strip()
            import json
            return json.loads(cleaned)
        except Exception as e:
            return {"error": f"Error generating marketing data: {str(e)}"}

    async def check_consistency(self, text, char_sheet, world_setting, model_name="models/gemini-3-flash-preview"):
        prompt = f"""
        당신은 대한민국 최고의 로맨스 소설 설정 검수자(Consistency Editor)입니다.
        [소설 내용]을 [설정값 및 관계도]와 비교하여 오류나 모순을 찾아내십시오.

        [설정값 및 관계도]
        - 인물 설정: {char_sheet}
        - 세계관 및 배경: {world_setting}

        [소설 내용]
        {text}

        [분석 항목]
        1. **이름 및 호칭 오류**: 인물의 이름이 틀리거나, 설정과 다른 호칭을 사용하는 경우.
        2. **캐릭터 붕괴**: 인물의 성격이나 행동 동기가 설정과 정면으로 배치되는 경우.
        3. **설정 모순**: 세계관 설정이나 이전 사건과 모순되는 전개가 있는 경우.
        4. **오탈자 및 비문**: 문맥상 어색하거나 잘못된 맞춤법이 있는 경우.

        [출력 JSON 구조]
        {{
            "name_errors": ["오류 내용 1", "오류 내용 2"],
            "plot_errors": ["오류 내용 1", "오류 내용 2"],
            "suggestions": ["개선 제안 1"]
        }}
        
        중요: 반드시 한국어로 답변하십시오. 영어는 일절 사용하지 말고 JSON 객체만 반환하십시오. (Output ONLY in Korean)
        """
        try:
            raw_text = await self._call_gem_with_retry(prompt, model_name)
            cleaned = raw_text.replace("```json", "").replace("```", "").strip()
            import json
            return json.loads(cleaned)
        except Exception as e:
            return {"error": f"Consistency check failed: {str(e)}"}

    async def perform_comprehensive_review(self, text, criteria="Consistency, Grammar, Creativity", model_name="models/gemini-3.1-pro-preview"):
        """
        Performs a deep review of the text based on specific criteria.
        Returns a JSON report with scores and detailed feedback.
        """
        prompt = f"""
        당신은 대한민국 최고의 엘리트 소설 편집자이자 비평가입니다. 다음 텍스트를 엄격하고 전문적으로 검토하십시오.

        [검토 기준]
        {criteria}
        - **묘사 vs 진술 (Show, Don't Tell)**: 감정이나 분위기를 단순히 설명하지 않고 행동과 오감을 통해 보여주고 있는지 확인하십시오.
        - **심리 묘사의 깊이 (Deep POV)**: 서사가 캐릭터의 시점에 얼마나 깊이 몰입해 있는지 분석하십시오.
        - **호흡과 완급 (Pacing)**: 장면의 의도에 맞게 문장의 호흡이 적절히 조절되는지 확인하십시오.

        [검토할 텍스트]
        {text}

        [출력 JSON 리뷰 리포트 형식]
        {{
            "scores": {{
                "consistency": <점수 1-100>,
                "grammar_flow": <점수 1-100>,
                "creativity": <점수 1-100>
            }},
            "feedback": {{
                "consistency": "세부적인 한국어 피드백...",
                "grammar_flow": "세부적인 한국어 피드백...",
                "creativity": "세부적인 한국어 피드백..."
            }},
            "overall_critique": "장면의 전반적인 완성도에 대한 한국어 요약 비평.",
            "improvement_suggestions": ["개선 제안 1", "개선 제안 2"],
            "recommended_chapters": [
                {{"chapter": 1, "reason": "이 챕터가 수정이 필요한 이유 설명 (여기서는 해당 분석 대상 챕터 번호 반환)"}}
            ]
        }}

        중요: 반드시 유효한 JSON 형식으로 출력하십시오. 모든 텍스트 값은 한국어로 작성하십시오. 영어는 절대 사용하지 마십시오.
        """
        try:
            # Use a smarter model if possible, defaulting to the requested one
            raw_text = await self._call_gem_with_retry(prompt, model_name)
            cleaned = raw_text.replace("```json", "").replace("```", "").strip()
            import json
            return json.loads(cleaned)
        except Exception as e:
             # Fallback to flash if Pro fails or not available
            try:
                raw_text = await self._call_gem_with_retry(prompt, "models/gemini-3-flash-preview")
                cleaned = raw_text.replace("```json", "").replace("```", "").strip()
                import json
                return json.loads(cleaned)
            except Exception as inner_e:
                return {"error": f"Review failed: {str(inner_e)}"}

    async def rewrite_story_segment(self, text, critique, char_sheet, world_setting, model_name="models/gemini-3.1-pro-preview", style_guide="", rag_context="") -> str:
        """
        Rewrites the story segment based on the provided critique and Story Bible.
        Ensures consistency, custom style guides, RAG style references, and improved quality.
        """
        rag_section = ""
        if rag_context and rag_context.strip():
            rag_section = f"\n\n[참조 데이터 (RAG 스타일 레퍼런스)]\n아래는 작가님이 지향하는 롤모델 소설의 스타일 레퍼런스 본문입니다. 이 참조작의 문체 호흡, 단어 선택 경향, 묘사 밀도를 자연스럽게 묻어나게 반영하십시오.\n---\n{rag_context}\n---"

        style_instruction = ""
        if style_guide and style_guide.strip():
            style_instruction = f"\n\n[스타일 가이드 지침 강제 적용]\n{style_guide}"

        prompt = f"""
        당신은 대한민국 최고의 소설 전문 편집자이자 대필 작가(Ghostwriter)입니다. 
        작가님이 제공한 [원본 원고]를 [비평 및 개선 목표]에 따라 더 높은 퀄리티로 개고(Rewrite)하십시오. 
        이 과정에서 반드시 [소설 설정], [스타일 가이드 지침], 그리고 [RAG 스타일 레퍼런스]를 철저히 준수해야 합니다.

        [소설 설정 - 고정 데이터]
        - 인물 설정: {char_sheet}
        - 세계관 및 배경: {world_setting}
        {style_instruction}
        {rag_section}

        [비평 및 개선 목표]
        {critique}

        [원본 원고]
        {text}

        [지시사항]
        1. 비평 포인트를 충실히 반영하십시오 (예: 묘사 강화, 설정 오류 수정).
        2. 원래의 주요 플롯 흐름은 유지하되 문체와 분위기를 지정된 스타일 가이드 및 RAG 문체 호흡을 참고하여 로맨틱하고 현대적으로 개선하십시오.
        3. 캐릭터의 목소리와 특징이 설정과 일치하는지 재확인하십시오.
        4. 영어 설명이나 인사말 없이 오직 **개고된 한국어 본문**만 출력하십시오.

        [개고 결과(Response)]:
        """
        try:
            return await self._call_gem_with_retry(prompt, model_name)
        except Exception as e:
            return f"Rewrite failed: {str(e)}"

    async def generate_cover_image(self, prompt: str):
        """
        Generates an image using the internal image model.
        """
        try:
            response = self.image_model.generate_content(prompt)
            if response.parts:
                for part in response.parts:
                    if hasattr(part, 'inline_data') and part.inline_data:
                         import base64
                         img_bytes = part.inline_data.data
                         img_str = base64.b64encode(img_bytes).decode("utf-8")
                         return {"image_base64": img_str}
                    if hasattr(part, 'image'):
                         import base64
                         from io import BytesIO
                         img = part.image
                         buffered = BytesIO()
                         img.save(buffered, format="PNG")
                         img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
                         return {"image_base64": img_str}
            return {"error": "No image generated."}
        except Exception as e:
            return {"error": f"Image generation failed: {str(e)}"}

    async def summarize_context(self, text, model_name="models/gemini-3-flash-preview"):
        prompt = f"""
        당신은 대한민국 최고의 소설 작가이자 요약 전문가입니다.
        다음 소설 장면을 3~5문장 내외의 긴밀한 요약문으로 작성하십시오.
        이 요약은 다음 장면을 쓸 때 AI가 기억(Memory)해야 할 핵심 정보가 됩니다.
        
        [지시사항]
        - 주요 사건, 캐릭터의 심경 변화, 인물 관계의 진전을 중심으로 요약하십시오.
        - 담백하고 명확한 한국어 문체로 작성하십시오.
        - 영어는 일절 사용하지 마십시오.

        [요약할 내용]
        {text}

        [요약 결과(Response)]:
        """
        try:
            return await self._call_gem_with_retry(prompt, model_name)
        except Exception as e:
            return f"Summary Error: {str(e)}"

    async def generate_story_content(self, prompt, temperature=0.7, model_name="models/gemini-3-flash-preview"):
        try:
            # We don't use the retry helper here because it has a fixed temperature/config
            # But we could extend it if needed. For now, just fix the identifier.
            current_model = model_name
            if "RAG" in current_model or "PostgreSQL" in current_model:
                current_model = "gemini-2.5-flash"
            if not current_model.startswith("models/"):
                current_model = f"models/{current_model}"
            model = genai.GenerativeModel(current_model)
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature,
                    max_output_tokens=4000
                )
            )
            return response.text
        except Exception as e:
            return f"Error: {str(e)}"

    async def evaluate_plot_potential(self, settings: dict, outline: str, model_name="models/gemini-3.1-pro-preview") -> dict:
        """
        Analyzes the plot outline and settings for commercial potential.
        Returns a JSON report.
        """
        prompt = f"""
        Act as a Veteran Editor-in-Chief of a top web novel platform.
        Analyze the following 'Romance Novel Plan' and predict its commercial success.

        [Story Settings]
        - Genre: {settings.get('genre')}
        - Mood: {settings.get('mood')}
        - Characters: {settings.get('characters')}
        - World Setting: {settings.get('world')}
        - Trends Applied: {settings.get('trends')}

        [Plot Outline]
        {outline[:15000]} 

        [Analysis Criteria]
        1. **Commercial Viability (0-100)**: Does it fit current market trends (e.g., Regret, Possession, Revenge, Cider)?
        2. **Target Audience**: Who will pay for this? (Age, Gender, Buying Power).
        3. **Binge-Reading Factor (0-100)**: Are the cliffhangers strong? Is the pacing fast?
        4. **SWOT Analysis**: Strengths, Weaknesses, Opportunities, Threats.

        [Output Format (JSON)]
        {{
            "commercial_score": <int 0-100>,
            "binge_score": <int 0-100>,
            "target_audience": {{
                "age": "e.g., 20-30s",
                "gender": "e.g., Female",
                "buying_power": "High/Medium/Low"
            }},
            "swot": {{
                "strengths": ["Point 1", "Point 2"],
                "weaknesses": ["Point 1", "Point 2"],
                "opportunities": ["Point 1", "Point 2"],
                "threats": ["Point 1", "Point 2"]
            }},
            "overall_review": "Comprehensive feedback (3-4 sentences).",
            "improvement_advice": "Key advice to increase success rate."
        }}

        IMPORTANT: Output values in Korean (한국어로 작성). Return ONLY raw JSON.
        """
        try:
            raw_text = await self._call_gem_with_retry(prompt, model_name)
            cleaned = raw_text.replace("```json", "").replace("```", "").strip()
            import json
            return json.loads(cleaned)
        except Exception as e:
            return {"error": f"Evaluation failed: {str(e)}"}

    async def generate_book_packaging(self, settings: dict, outline: str, model_name="models/gemini-3.1-pro-preview") -> dict:
        """
        Generates Title, Blurb (Intro), and Keywords.
        """
        prompt = f"""
        당신은 대한민국 최고의 베스트셀러 웹소설 편집자입니다.
        다음 소설을 위한 '판매 패키지(북 패키징)'를 기획해 주세요.
        
        [장르] {settings.get('genre')}
        [트렌드 키워드] {settings.get('trends')}
        [작품 분위기] {settings.get('mood')}
        [인물 관계성] {settings.get('characters')}
        [세계관 배경] {settings.get('world')}
        
        [소설 전체 줄거리(요약)]
        {outline[:300000]}

        [지시사항]
        1. **제안 제목**: 트렌드를 반영하여 독자를 유혹할 수 있는 5가지 제목 (예: "그녀를 버리기로 결정했다", "레벨업하는 악녀")
        2. **책 소개문(Blurb)**: 플랫폼 메인 화면에 게시될 강렬한 3문단 분량의 소개문.
           - 설정된 [작품 분위기]와 [인물 관계성]이 선명하게 드러나야 합니다.
           - 애절한 분위기라면 가슴 아프게, 달콤한 분위기라면 설레게 서술하십시오.
        3. **핵심 키워드**: 검색 및 노출 최적화를 위한 10개의 해시태그 #키워드.

        [출력 JSON 형식]
        {{
            "titles": ["제목 1", "제목 2", ...],
            "blurb": "소개문 본문...",
            "keywords": ["#키워드1", "#키워드2", ...]
        }}
        
        중요: 반드시 한국어로 답변하십시오. 영어 설명 없이 오직 유효한 JSON 객체만 반환하십시오.
        """
        try:
            raw_text = await self._call_gem_with_retry(prompt, model_name, max_tokens=8192)
            cleaned = raw_text.replace("```json", "").replace("```", "").strip()
            import json
            return json.loads(cleaned)
        except Exception as e:
            return {"error": f"Packaging failed: {str(e)}"}

    async def auto_improve_plot(self, settings: dict, outline: str, advice: str, model_name="models/gemini-3.1-pro-preview") -> str:
        """
        Rewrites the plot outline to incorporate specific improvement advice.
        """
        prompt = f"""
        당신은 대한민국 최고의 소설 전문 기획자이자 편집자입니다.
        제시된 [전문가 개선 조언]을 바탕으로 기존의 [소설 줄거리]를 더 상업적으로 성공할 수 있도록 개고하십시오.

        [소설 기본 설정]
        - 장르/분위기: {settings.get('genre')} / {settings.get('mood')}
        - 인물 설정: {settings.get('characters')}
        - 세계관: {settings.get('world')}

        [현재 소설 줄거리(플롯)]
        {outline}

        [전문가 개선 조언]
        {advice}

        [지시사항]
        조언을 충실히 반영하여 더욱 흡입력 있고 전개가 매끄러운 줄거리로 재구성하십시오.
        기존의 구조(JSON 또는 리스트 형태)를 유지하되 내용은 보강하십시오.
        어떠한 경우에도 한국어로만 답변하십시오. (Output ONLY in Korean)
        """
        try:
            return await self._call_gem_with_retry(prompt, model_name)
        except Exception as e:
            return f"Improvement failed: {str(e)}"

    async def rewrite_improved_content(self, original_text: str, critique_json: dict, model_name="models/gemini-3.1-pro-preview") -> str:
        """
        Rewrites the story content based on the critique to improve quality.
        Targeting 'Self-Healing' workflow.
        """
        critique_text = critique_json.get("overall_critique", "")
        suggestions = "\n".join(critique_json.get("improvement_suggestions", []))
        
        prompt = f"""
        당신은 대한민국 최고의 베스트셀러 로맨스 작가이자 리라이팅 전문가입니다. 
        제시된 [전문가 비평 및 진단] 결과에 따라 원본 텍스트를 더 생동감 있고 몰입도 높게 개고하십시오.

        [전문가 비평 및 진단]
        {critique_text}
        
        [적용해야 할 세부 개선 사항]
        {suggestions}

        [원본 원고 텍스트]
        {original_text}

        [지시사항]
        1. **묘사 강화 (Show, Don't Tell)**: 추상적인 감정을 인물의 행동, 감각, 신체적 반응으로 변환하십시오.
        2. **호흡과 전개**: 비평에서 지적된 속도감(Pacing) 문제를 해결하십시오.
        3. **대사 최적화**: 인물의 성격이 드러나도록 대사를 더 자연스럽고 매력적으로 수정하십시오.
        4. **핵심 줄거리 유지**: 사건의 큰 흐름은 바꾸지 않되 연출의 밀도를 높이십시오.

        오직 개고된 한국어 원고 본문만 출력하십시오. 영어 설명은 절대 금지됩니다. (Output ONLY in Korean)
        """
        try:
            return await self._call_gem_with_retry(prompt, model_name)
        except Exception as e:
            return f"Rewrite failed: {str(e)}"

    async def generate_polish_options(
        self, 
        paragraph: str, 
        model_name: str = 'models/gemini-3-flash-preview', 
        rag_context: str = None
    ) -> dict:
        
        # RAG 스타일 참고 텍스트 섹션 준비
        rag_section = ""
        if rag_context and rag_context.strip():
            rag_section = f"""
[참조 데이터 (RAG 스타일 레퍼런스)]
아래 내용은 사용자가 창작하고자 하는 소설의 롤모델이 되는 실제 원본 로맨스 소설(할리퀸 등)의 스타일 레퍼런스 본문 및 설정 정보입니다.
이 참조작의 문체 특성(대사 호흡, 서술형 문장의 길이, 단어 선택 경향, 전반적인 묘사 밀도)을 깊이 분석하여, 
각 교정 버전(A, B, C안)을 작성할 때 이 문체적 매력이 자연스럽게 베어들도록 가이드라인 삼으십시오.
---
{rag_context}
---
"""

        prompt = f"""당신은 베스트셀러 로맨스 소설 전문 윤문가입니다.
주어진 원문의 의미, 인물 간의 관계, 서사 흐름을 100% 보전하면서, 아래 3가지 문체 스타일에 맞게 각각 재창조(Transform)된 교정안을 작성하십시오.
{rag_section}
[원문]
{paragraph}

[교정안 스타일 미션]
- A안 (감성/아련): 참조작의 고유한 정서와 아련함을 조화시켜, 섬세한 심리 묘사와 서정적이고 감성적인 로맨스 문체로 다듬어 주십시오.
- B안 (관능/밀착): 참조작의 생생하고 밀도 높은 묘사력을 녹여내어, 시각과 촉각을 자극하는 농밀하고 관능적인 분위기(가빠지는 호흡, 은밀한 체온 접촉 등)를 돋보이게 교정하십시오.
- C안 (강렬/도발): 참조작 특유의 인물 간의 대화 긴장감과 상충하는 감정선을 반영하여, 숨막히는 갈등과 직설적이고 도발적인 감정 표출을 위주로 텐션이 폭발하듯 묘사해 주십시오.

[출력 요구사항]
반드시 아래 JSON 형식을 정확히 지켜 답변하십시오. 다른 인사말이나 설명은 절대 추가하지 마십시오.

{{
    "A안 (감성/아련)": "교정된 텍스트...",
    "B안 (관능/밀착)": "교정된 텍스트...",
    "C안 (강렬/도발)": "교정된 텍스트..."
}}
"""
        try:
            res_text = await self._call_gem_with_retry(prompt, model_name)
            import json, re
            match = re.search(r'\{.*\}', res_text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        except Exception as e:
            print(f"Gemini Polish Option failed: {e}")
        
        # Fallback
        return {
            "A안 (감성/아련)": f"{paragraph} (감성적인 묘사가 추가된 문단)",
            "B안 (관능/밀착)": f"{paragraph} (관능적이고 세밀한 묘사가 추가된 문단)",
            "C안 (강렬/도발)": f"{paragraph} (강렬하고 텐션 높은 묘사가 추가된 문단)"
        }

    async def resolve_consistency_via_settings(self, char_sheet, world_setting, plot_errors, model_name="models/gemini-3-flash-preview"):
        prompt = f"""
        당신은 대한민국 최고의 로맨스 소설 설정 검수자이자 편집자입니다.
        현재 소설 본문에서 발견된 모순점(Plot Conflicts)을 매끄럽게 해결하기 위해,
        기존 설정 데이터에 모순을 해결해줄 보완 정보를 반영하여 최종적으로 **통합/수정된 전체 캐릭터 시트 및 세계관 데이터**를 제공해주십시오.

        [기존 캐릭터 설정 전체]
        {char_sheet}

        [기존 세계관 및 배경 설정 전체]
        {world_setting}

        [발견된 모순점]
        {plot_errors}

        [목표]
        1. 기존 캐릭터 설정과 세계관 설정을 기반으로 하되, 지적된 모순점이 자연스럽게 해결되도록 관련 내용을 본문에 녹여내거나 수정하여 업데이트하십시오.
        2. 기존 정보 중 모순과 무관한 핵심 캐릭터 설정, 외모, 배경 정보 등은 절대 소실시키지 말고 고스란히 보존하십시오.
        3. 단순 덧붙이기가 아닌, 기존 설정의 맥락에 완벽히 병합(Merge)하여 일관되고 깔끔한 하나의 문서로 완성해 반환하십시오.

        [출력 JSON 구조]
        {{
            "char_sheet_merged": "모순이 완전히 조치된 최종 캐릭터 설정 전체 텍스트 (이전 설정 내용 + 모순 보완 병합)",
            "world_setting_merged": "모순이 완전히 조치된 최종 세계관 설정 전체 텍스트 (이전 설정 내용 + 모순 보완 병합)"
        }}

        중요: 반드시 JSON 객체로만 응답하십시오. (Output ONLY JSON)
        """
        try:
            res_text = await self._call_gem_with_retry(prompt, model_name)
            import json, re
            match = re.search(r'\{.*\}', res_text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        except Exception as e:
            print(f"resolve_consistency_via_settings failed: {e}")
        return {"char_sheet_merged": char_sheet, "world_setting_merged": world_setting}

    async def resolve_consistency_via_story(self, text, char_sheet, world_setting, plot_errors, style_guide, rag_context="", model_name="models/gemini-3.1-pro-preview"):
        prompt = f"""
        당신은 대한민국 최고의 웹소설 작가입니다.
        현재 소설 본문에서 아래와 같은 모순점(Plot Conflicts)이 지적되었습니다.
        기존의 캐릭터 설정 및 세계관 규칙에 위배되지 않도록, 해당 소설 본문을 자연스럽게 다시 작성(Rewrite)해 주십시오.

        [기존 캐릭터 설정]
        {char_sheet}

        [기존 세계관 및 배경 설정]
        {world_setting}

        [스타일 가이드 및 집필 지침]
        {style_guide}

        [RAG 참고 문맥]
        {rag_context}

        [발견된 모순점]
        {plot_errors}

        [원래 소설 본문]
        {text}

        [요구사항]
        - 지적된 모순점을 완전히 해결하십시오.
        - 본문의 흐름, 스타일 가이드, 그리고 RAG 맥락을 최대한 존중하여 자연스러운 톤으로 재작성하십시오.
        - 오직 수정된 소설 본문 텍스트만 출력하십시오. 추가적인 부연 설명이나 마크다운 코드 블록(```)은 절대 포함하지 마십시오.
        """
        try:
            res = await self._call_gem_with_retry(prompt, model_name)
            import re
            res_clean = re.sub(r"^```[a-zA-Z]*\n", "", res)
            res_clean = re.sub(r"\n```$", "", res_clean)
            return res_clean.strip()
        except Exception as e:
            print(f"resolve_consistency_via_story failed: {e}")
            return text

    async def sync_outline_with_settings(self, char_sheet, world_setting, blurb, plot_outline, model_name="models/gemini-3.1-pro-preview"):
        prompt = f"""
        당신은 대한민국 최고의 소설 기획자이자 편집자입니다.
        현재 남주인공, 여주인공의 캐릭터 설정이나 세계관 규칙이 업데이트되었습니다.
        이에 맞추어 기존의 [책 소개(Blurb)]와 [플롯 개요(Plot Outline)]가 모순 없이 조화를 이루도록 미세 교정해 주십시오.

        [업데이트된 캐릭터 설정]
        {char_sheet}

        [업데이트된 세계관 설정]
        {world_setting}

        [기존 책 소개 (Blurb)]
        {blurb}

        [기존 플롯 개요 (Plot Outline)]
        {plot_outline}

        [목표 및 절대 안전 원칙]
        1. 기존 책 소개 및 플롯 개요에 담긴 사건의 흐름, 챕터별 구성, 고유한 연출 등 핵심 줄거리는 절대 마음대로 삭제하거나 어지럽히지 마십시오.
        2. 오직 바뀐 인물 설정(예: 7년 전 아는 사이, 치욕스러운 사건 등)과 배치되는 모순점만 자연스럽게 매칭되도록 최소한의 수정/보완 작업만 수행하십시오.
        3. 변경 사항이 없을 경우 기존의 텍스트를 그대로 반환하십시오.

        [출력 JSON 구조]
        {{
            "blurb_synced": "업데이트된 캐릭터/세계관 설정과 완벽히 동기화된 책 소개 전체 텍스트",
            "plot_outline_synced": "업데이트된 캐릭터/세계관 설정과 완벽히 동기화된 플롯 개요 전체 텍스트"
        }}

        중요: 반드시 JSON 객체로만 응답하십시오. (Output ONLY JSON)
        """
        try:
            res_text = await self._call_gem_with_retry(prompt, model_name)
            import json, re
            match = re.search(r'\{.*\}', res_text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        except Exception as e:
            print(f"sync_outline_with_settings failed: {e}")
        return {"blurb_synced": blurb, "plot_outline_synced": plot_outline}

    async def check_spell(self, text: str, model_name: str = "models/gemini-2.5-flash") -> str:
        """
        한국어 맞춤법, 띄어쓰기 및 소설 문맥 교정
        """
        if not self.api_key:
            return "Gemini API Key가 구성되지 않았습니다."

        prompt = f"""당신은 한국어 소설 및 도서 전문 편집기획자입니다.
제공된 소설 본문의 맞춤법, 띄어쓰기, 문맥상 비문, 흐름상 지나치게 어색한 번역체 등을 교정하고 이유를 설명하는 마크다운 형식의 정밀 리포트를 작성해 주세요.

[교정 가이드라인]
1. **맞춤법/오탈자**: 소설 속 인물 이름이나 특수 고유 명사를 제외하고 표준 맞춤법 및 오탈자를 정밀 교정합니다.
2. **띄어쓰기**: 가독성을 높이고 문법에 어긋나지 않도록 띄어쓰기를 지적합니다.
3. **문장/표현 다듬기**: 로맨스 장르 특성이나 문맥에 잘 부합하도록 비문, 어색한 연결, 번역투를 세련된 문장으로 다듬습니다.

표(Table) 또는 명확한 목록을 사용하여 원본(오류가 있는 부분)과 교정안, 이유를 직관적으로 비교할 수 있도록 해 주시고, 마지막에 전체적인 맞춤법/가독성 총평을 한글로 제공해 주세요.

[검사 대상 소설 텍스트]
{text}

[맞춤법 및 문장 교정 리포트]
"""
        try:
            return await self._call_gem_with_retry(prompt, model_name)
        except Exception as e:
            return f"맞춤법 검사 중 오류가 발생했습니다: {str(e)}"

gemini_service = GeminiService()


