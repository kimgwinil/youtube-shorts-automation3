import base64
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib import error, request

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path.cwd()
TOPIC_CATEGORY = os.getenv("LONGFORM_TOPIC_CATEGORY", "life").strip().lower()
DEFAULT_HISTORY_NAME = f"topic-history-{TOPIC_CATEGORY}.json"
HISTORY = Path(os.getenv("LONGFORM_HISTORY_FILE", Path(__file__).with_name(DEFAULT_HISTORY_NAME)))
OUT = ROOT / "output" / datetime.now().strftime("%Y%m%d")
WIDTH, HEIGHT, FPS = 1920, 1080, 30
SCENE_IMAGE_MAX_WORKERS = max(1, min(4, int(os.getenv("SCENE_IMAGE_MAX_WORKERS", "2"))))
IMAGE_PROVIDER = os.getenv("IMAGE_PROVIDER", "gemini").lower()
BGM_ENABLED = os.getenv("ENABLE_BGM", "false").lower() == "true"
SLIDE_CAPTIONS_ENABLED = os.getenv("ENABLE_SLIDE_CAPTIONS", "false").lower() == "true"
BURN_IN_SUBTITLES = os.getenv("BURN_IN_SUBTITLES", "true").lower() == "true"
UPLOAD_YOUTUBE_CAPTIONS = os.getenv("UPLOAD_YOUTUBE_CAPTIONS", "false").lower() == "true"
SLIDE_MOTION_ENABLED = os.getenv("ENABLE_SLIDE_MOTION", "false").lower() == "true"
HEYGEN_BASE_URL = os.getenv("HEYGEN_BASE_URL", "https://api.heygen.com").rstrip("/")
HEYGEN_ENABLED = os.getenv("HEYGEN_ENABLED", "false").lower() == "true"
HEYGEN_SCENE_INDICES = os.getenv("HEYGEN_SCENE_INDICES", "1,17")
HEYGEN_MIN_REPLACED_SCENES = int(os.getenv("HEYGEN_MIN_REPLACED_SCENES", "1"))
HEYGEN_RESOLUTION = os.getenv("HEYGEN_RESOLUTION", "1080p")
HEYGEN_ASPECT_RATIO = os.getenv("HEYGEN_ASPECT_RATIO", "16:9")
HEYGEN_POLL_INTERVAL = int(os.getenv("HEYGEN_POLL_INTERVAL", "10"))
HEYGEN_POLL_TIMEOUT = int(os.getenv("HEYGEN_POLL_TIMEOUT", "900"))

LIFE_TOPICS = [
    {
        "id": "study-score-plateau",
        "topic": "교육: 공부를 오래 해도 성적이 안 오르는 이유",
        "title": "공부를 오래 해도 성적이 안 오르는 이유",
        "description": "공부 시간이 늘었는데 성적이 오르지 않는다면, 문제는 의지보다 공부 방식일 수 있습니다.\n\n오답 분석, 간격 복습, 작은 테스트가 성적을 바꾸는 이유를 설명합니다.\n\n#공부법 #성적향상 #교육 #복습법 #학습전략",
        "tags": ["공부법", "성적향상", "교육", "복습법", "학습전략", "시험공부"],
        "subject": "Korean student studying late at a desk, tired but focused, realistic documentary style",
        "problem": "공부 시간은 길지만 틀린 문제를 고치는 과정이 부족함",
        "solution": "오답 분석, 간격 복습, 작은 테스트로 피드백 루프를 만드는 것",
        "example": "공부 시간을 늘렸는데도 같은 유형의 문제를 계속 틀리는 학생",
    },
    {
        "id": "meeting-no-decision",
        "topic": "조직문화: 회의는 많은데 왜 결정은 안 날까?",
        "title": "회의는 많은데 왜 결정은 안 날까?",
        "description": "회의가 많아도 결정이 나지 않는 조직에는 공통점이 있습니다.\n\n목적, 결정권자, 다음 행동이 없으면 회의는 일하는 척하는 시간이 됩니다.\n\n#조직문화 #회의문화 #업무효율 #리더십 #생산성",
        "tags": ["조직문화", "회의문화", "업무효율", "리더십", "생산성", "직장생활"],
        "subject": "Korean office meeting room, many documents, people unable to decide, realistic documentary style",
        "problem": "회의 목적, 결정권자, 다음 행동이 불명확함",
        "solution": "회의 전 결정 질문을 정하고 끝에는 담당자와 마감일을 남기는 것",
        "example": "한 시간 동안 회의했지만 담당자와 마감일이 정해지지 않은 팀",
    },
    {
        "id": "online-review-trust",
        "topic": "소비자이슈: 온라인 리뷰를 어디까지 믿어야 할까?",
        "title": "온라인 리뷰를 어디까지 믿어야 할까?",
        "description": "리뷰가 많다고 항상 믿을 수 있는 것은 아닙니다.\n\n좋은 리뷰와 위험한 리뷰를 구분하려면 별점보다 패턴과 구체성을 봐야 합니다.\n\n#온라인리뷰 #소비자이슈 #쇼핑팁 #리뷰분석 #플랫폼",
        "tags": ["온라인리뷰", "소비자이슈", "쇼핑팁", "리뷰분석", "플랫폼"],
        "subject": "Korean consumer reviewing online shopping ratings on a laptop, realistic documentary style",
        "problem": "별점만 보고 구매하면 광고성 리뷰와 반복 패턴을 놓칠 수 있음",
        "solution": "구체적인 사용 후기, 반복 표현, 낮은 별점의 이유를 함께 보는 것",
        "example": "별점만 보고 샀다가 실제 사용 후기가 부족하다는 것을 뒤늦게 알게 된 소비자",
    },
    {
        "id": "sleep-quality",
        "topic": "건강생활: 오래 자도 피곤한 이유",
        "title": "오래 자도 피곤한 이유",
        "description": "수면 시간은 충분한데 계속 피곤하다면, 문제는 잠의 양이 아니라 질일 수 있습니다.\n\n수면의 질을 떨어뜨리는 습관과 회복감을 높이는 기본 원칙을 설명합니다.\n\n#수면 #건강생활 #피로 #생활습관 #수면의질",
        "tags": ["수면", "건강생활", "피로", "생활습관", "수면의질"],
        "subject": "Korean office worker waking up tired in the morning, realistic documentary style",
        "problem": "불규칙한 수면 시간, 늦은 화면 사용, 낮은 수면의 질",
        "solution": "일정한 기상 시간, 빛 노출 조절, 잠들기 전 루틴을 만드는 것",
        "example": "잠은 오래 잤지만 아침마다 개운하지 않은 직장인",
    },
]

MEDICAL_COMMON_SENSE_TOPICS = [
    {
        "id": "blood-pressure-basics",
        "topic": "의학상식: 혈압 수치를 볼 때 꼭 알아야 할 기본",
        "title": "혈압 수치, 숫자만 보면 놓치는 것들",
        "description": "혈압은 한 번의 숫자보다 반복 측정과 생활 습관 맥락이 중요합니다.\n\n가정혈압 측정법, 기록 습관, 병원 상담이 필요한 신호를 알기 쉽게 설명합니다.\n\n#혈압 #의학상식 #건강관리 #생활습관 #건강정보",
        "tags": ["혈압", "의학상식", "건강관리", "생활습관", "건강정보"],
        "subject": "Korean adult checking blood pressure at home with a digital monitor, realistic documentary style",
        "problem": "혈압을 한 번만 재고 정상 또는 위험으로 단정하기 쉬움",
        "solution": "올바른 자세로 반복 측정하고 기록을 바탕으로 전문가와 상담하는 것",
        "example": "집에서 잰 혈압과 병원에서 잰 혈압이 달라 혼란스러운 직장인",
    },
    {
        "id": "medication-label-basics",
        "topic": "의학상식: 약 봉투와 설명서에서 먼저 봐야 할 것",
        "title": "약 설명서, 이것부터 확인하세요",
        "description": "약은 이름보다 복용 방법, 주의사항, 중복 성분 확인이 더 중요할 때가 많습니다.\n\n약 봉투와 설명서를 읽는 기본 순서를 생활 속 예시로 정리합니다.\n\n#약복용 #의학상식 #복약지도 #건강정보 #약설명서",
        "tags": ["약복용", "의학상식", "복약지도", "건강정보", "약설명서"],
        "subject": "Korean patient reading medication instructions at a pharmacy counter, realistic documentary style",
        "problem": "약 이름만 보고 복용 시간과 주의사항을 놓칠 수 있음",
        "solution": "복용 횟수, 식전 식후, 중복 성분, 이상 반응 안내를 먼저 확인하는 것",
        "example": "감기약과 진통제를 함께 먹어도 되는지 몰라 약국에서 상담하는 사람",
    },
    {
        "id": "blood-sugar-signals",
        "topic": "의학상식: 혈당 관리에서 놓치기 쉬운 생활 신호",
        "title": "혈당 관리, 생활 신호부터 보세요",
        "description": "혈당은 식사, 수면, 활동량, 스트레스의 영향을 함께 받습니다.\n\n일상에서 관찰할 수 있는 변화와 검진 결과를 해석할 때의 기본 원칙을 설명합니다.\n\n#혈당 #의학상식 #건강검진 #생활습관 #건강정보",
        "tags": ["혈당", "의학상식", "건강검진", "생활습관", "건강정보"],
        "subject": "Korean adult reviewing a health checkup report at a kitchen table, realistic documentary style",
        "problem": "검진 수치 하나만 보고 생활 패턴의 영향을 놓치기 쉬움",
        "solution": "식사, 활동, 수면 기록과 검진 결과를 함께 보고 전문가 상담을 받는 것",
        "example": "야근과 간식이 늘어난 뒤 건강검진 혈당 수치가 올라 걱정하는 사람",
    },
    {
        "id": "dehydration-basics",
        "topic": "의학상식: 탈수를 가볍게 보면 안 되는 이유",
        "title": "탈수, 목마름만의 문제가 아닙니다",
        "description": "탈수는 갈증뿐 아니라 피로감, 어지러움, 소변 색 변화로도 나타날 수 있습니다.\n\n더운 날, 운동 후, 고령자에게 특히 중요한 수분 관리 기본을 정리합니다.\n\n#탈수 #의학상식 #수분관리 #건강정보 #생활건강",
        "tags": ["탈수", "의학상식", "수분관리", "건강정보", "생활건강"],
        "subject": "Korean older adult drinking water after a walk in warm weather, realistic documentary style",
        "problem": "갈증이 심하지 않으면 탈수 가능성을 놓칠 수 있음",
        "solution": "활동량과 날씨에 맞춰 수분을 보충하고 위험 신호가 있으면 진료를 받는 것",
        "example": "더운 날 산책 후 어지러움을 느껴 휴식과 수분 보충이 필요한 어르신",
    },
]

TOPICS_BY_CATEGORY = {
    "life": LIFE_TOPICS,
    "medical": MEDICAL_COMMON_SENSE_TOPICS,
    "medical_common_sense": MEDICAL_COMMON_SENSE_TOPICS,
}
TOPICS = TOPICS_BY_CATEGORY.get(TOPIC_CATEGORY, LIFE_TOPICS)

LAYOUT_TITLES = [
    "오늘의 질문",
    "겉으로 보이는 문제",
    "실제 원인",
    "첫 번째 원인",
    "두 번째 원인",
    "세 번째 원인",
    "놓치기 쉬운 지점",
    "문제가 커지는 순간",
    "위험도를 나누는 기준",
    "해결의 순서",
    "좋은 방식의 공통점",
    "간단한 예시",
    "실행은 연결입니다",
    "오늘 바로 할 일",
    "작은 실험",
    "마지막 점검",
    "결론",
]

LAYOUT_TITLES_EN = [
    "Today's Question",
    "The Visible Problem",
    "Root Cause",
    "First Cause",
    "Second Cause",
    "Third Cause",
    "What's Often Missed",
    "Escalation Point",
    "Risk Assessment",
    "Steps to Resolve",
    "Common Patterns",
    "Simple Example",
    "Execution Connects",
    "Action Item Today",
    "Small Experiment",
    "Final Check",
    "Conclusion",
]


def _find_cjk_font():
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                ImageFont.truetype(path, size=20, index=0)
                return path
            except Exception:
                continue
    return None


_CJK_FONT_PATH = _find_cjk_font()


def _has_korean(text):
    return any("가" <= ch <= "힣" or "ᄀ" <= ch <= "ᇿ" for ch in text)


def load_history():
    if not HISTORY.exists():
        return []
    return json.loads(HISTORY.read_text(encoding="utf-8"))


def save_history(history):
    HISTORY.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def generate_topic(history):
    used_topics = [x.get("topic", "") for x in history if x.get("topic")]
    prompt = {
        "role": "user",
        "content": (
            "Create one fresh Korean YouTube longform explainer topic as strict JSON. "
            "Avoid every used topic. The tone should be informative, practical, and suitable for a Korean audience. "
            "Choose a concrete everyday problem that can be shown visually in realistic slides. "
            "Do not choose broad abstract topics, vague culture commentary, politics, disasters, celebrities, or medical diagnosis. "
            "The topic must naturally support 17 different visual scenes with Korean people, places, objects, or actions. "
            "Fields required: id, topic, title, description, tags, subject, problem, solution, example. "
            "description must include two short paragraphs and 5 Korean hashtags. "
            "tags must be a list of 5 to 7 Korean strings. "
            "subject must be an English visual prompt for realistic Korean documentary imagery, with a specific location and visible main subject. "
            "problem, solution, and example must be concise Korean phrases using standard Korean spelling. "
            "example must describe a concrete Korean real-life situation and must not include English. "
            "Do not use slang, intentionally misspelled Korean, or unclear abbreviations.\n\n"
            f"Used topics:\n{json.dumps(used_topics, ensure_ascii=False)}"
        ),
    }
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_TEXT_MODEL", "gpt-4o-mini"),
        messages=[
            {
                "role": "system",
                "content": "You return only valid JSON. Do not include markdown fences or commentary.",
            },
            prompt,
        ],
        temperature=0.85,
    )
    raw = response.choices[0].message.content.strip()
    topic = json.loads(raw)
    required = {"id", "topic", "title", "description", "tags", "subject", "problem", "solution", "example"}
    missing = sorted(required - set(topic))
    if missing:
        raise RuntimeError(f"Generated topic is missing fields: {missing}")
    if topic["topic"] in used_topics:
        raise RuntimeError("Generated topic duplicated a used topic")
    return topic


def pick_topic(history):
    used = {x.get("topic") for x in history}
    for topic in TOPICS:
        if topic["topic"] not in used:
            return topic
    return generate_topic(history)


def _first_sentence(text):
    """Return a subtitle-sized opening sentence without cutting short quoted questions."""
    parts = re.findall(r".+?(?:[.?!。！？]+[\"'’”)]*|$)", text.strip())
    if not parts:
        return text.strip()
    caption = ""
    for part in parts:
        caption = (caption + " " + part.strip()).strip()
        if len(caption) >= 24:
            break
    if len(caption) > 72:
        shortened = caption[:72].rsplit(" ", 1)[0].strip()
        return shortened or caption[:72].strip()
    return caption


def scene_image_provider(index):
    if IMAGE_PROVIDER in {"openai", "gemini"}:
        return IMAGE_PROVIDER
    if IMAGE_PROVIDER == "mixed":
        return "openai" if index % 2 == 0 else "gemini"
    return "gemini"


def generate_narrations(topic):
    from google import genai

    client = genai.Client(
        api_key=os.environ.get("GEMINI_API_KEY") or os.environ["GOOGLE_API_KEY"]
    )
    prompt = (
        "한국어 유튜브 롱폼 영상의 17개 장면 나레이션을 작성하세요.\n\n"
        f"주제: {topic['title']}\n"
        f"핵심 문제: {topic['problem']}\n"
        f"해결 방향: {topic['solution']}\n"
        f"예시 상황: {topic.get('example', '')}\n\n"
        "규칙:\n"
        "- 도입 방식, 문장 구조, 표현을 주제에 맞게 완전히 새롭게 작성할 것\n"
        "- 고정 반복 표현 절대 금지 — 매 영상이 같은 패턴처럼 들리면 안 됩니다\n"
        "- 각 나레이션은 2~3문장, 자연스럽고 생동감 있는 한국어로 작성\n\n"
        "장면 품질 규칙:\n"
        "- 각 장면은 서로 다른 상황, 장소, 행동을 말해야 합니다\n"
        "- 추상적인 말만 하지 말고, 화면에 보일 수 있는 사람·사물·행동을 포함하세요\n"
        "- 같은 문장 시작이나 같은 결론을 반복하지 마세요\n"
        "- 자막으로 쓸 첫 문장은 24자에서 48자 사이의 완결된 한국어 문장으로 시작하세요\n\n"
        "title 필드 규칙 (매우 중요):\n"
        "- 반드시 2~4단어의 짧은 키워드형 제목만 허용\n"
        "- 문장, 질문, 긴 설명 절대 금지\n"
        "- 올바른 예: '디지털 피로', '수면 방해', '해결 순서', '오늘의 실천'\n"
        "- 잘못된 예: '혹시 당신도 디지털 좀비인가요?', '휴식이 없는 휴식'\n\n"
        "아래 JSON 배열 형식으로만 응답 (마크다운 코드블록 금지):\n"
        '[{"title": "짧은 키워드 제목", "title_en": "Short keyword title", '
        '"narration": "나레이션 전문"}, ...]\n\n'
        "17개 장면 역할 (순서 고정):\n"
        "1.도입 2.표면적 문제 3.진짜 원인 4.원인1 5.원인2 6.원인3 "
        "7.사람들이 놓치는 것 8.상황이 악화되는 순간 9.위험 판단 기준 10.해결 순서 "
        "11.효과적인 방식의 공통점 12.실제 사례 13.실행의 연결고리 "
        "14.지금 당장 할 일 15.작은 실험 제안 16.최종 점검 17.결론"
    )
    response = client.models.generate_content(
        model=os.getenv("GEMINI_TEXT_MODEL", "gemini-2.5-flash"),
        contents=prompt,
    )
    raw = response.text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    data = json.loads(raw)
    if len(data) != 17:
        raise RuntimeError(f"Expected 17 scenes from Gemini, got {len(data)}")
    return data


def _build_scenes_fallback(topic):
    example = topic.get("example") or f"{topic['problem']} 때문에 같은 문제가 반복되는 상황"
    narrations = [
        f"{topic['title']}에 대해 많은 사람이 궁금해하지만 제대로 설명된 적이 없습니다. 오늘은 이 문제의 핵심을 짚어보겠습니다.",
        f"눈에 보이는 현상에만 집중하면 {topic['problem']}이라는 진짜 문제를 놓치게 됩니다.",
        "반복되는 패턴에는 반드시 이유가 있습니다. 의지의 문제가 아니라 구조의 문제일 가능성이 높습니다.",
        "첫 번째로 살펴볼 것은 판단 기준이 불분명한 상황입니다. 기준이 없으면 사람은 습관대로 움직이게 됩니다.",
        "두 번째는 피드백 속도의 문제입니다. 결과를 늦게 확인할수록 같은 실수를 반복할 확률이 높아집니다.",
        "세 번째는 기록의 부재입니다. 기록하지 않으면 무엇이 달라졌는지 알 수 없고, 개선도 어렵습니다.",
        "작은 것을 무시하는 습관이 쌓이면 나중에 큰 문제로 돌아옵니다. 이 지점을 많은 사람이 그냥 지나칩니다.",
        "문제를 인식하고도 미루는 순간 상황은 더 복잡해집니다. 타이밍이 중요한 이유가 여기 있습니다.",
        "얼마나 자주 발생하는지와 한 번 발생했을 때 영향이 얼마나 큰지, 두 가지를 함께 봐야 합니다.",
        f"{topic['solution']}이 핵심입니다. 문제를 잘게 나누고, 원인을 확인하고, 작은 것부터 실행하세요.",
        "실제로 효과가 있는 방식에는 공통점이 있습니다. 기록되고, 비교되고, 다음 행동으로 이어지는 것입니다.",
        f"{example}처럼 보이는 것과 실제 원인은 다를 수 있습니다. 현상이 아닌 원인을 보세요.",
        "실행은 한 번으로 끝나지 않습니다. 확인이 행동으로, 행동이 다시 확인으로 이어져야 합니다.",
        "지금 당장 할 수 있는 한 가지는 문제를 구체적인 문장으로 써보는 것입니다.",
        "전부 바꾸려 하지 말고 영향이 가장 큰 행동 하나만 골라서 바꿔보세요.",
        "세 가지만 확인하세요. 원인이 구체적인가, 행동이 작은가, 결과를 확인할 시간이 있는가.",
        f"{topic['solution']}을 꾸준히 실천할 때 문제는 두려움이 아닌 관리 가능한 과제가 됩니다.",
    ]
    details = [
        "실제 생활 장면을 기준으로 왜 이런 일이 반복되는지 차근차근 살펴보겠습니다.",
        "겉으로는 작은 불편처럼 보이지만, 같은 상황이 반복되면 비용과 스트레스가 커집니다.",
        "그래서 오늘은 감정적인 조언보다 실제로 확인할 수 있는 기준을 중심으로 설명하겠습니다.",
        "이 장면에서는 무엇을 먼저 봐야 하는지, 어떤 신호를 놓치면 안 되는지 분명히 짚어보겠습니다.",
        "비슷해 보이는 선택지도 기준이 다르면 전혀 다른 결과를 만들 수 있습니다.",
        "생활 속에서 자주 마주치는 사례를 떠올리면 이 차이가 훨씬 쉽게 이해됩니다.",
        "작은 요소 하나가 전체 흐름을 바꾸기 때문에, 사소해 보이는 부분도 따로 확인해야 합니다.",
        "이때부터는 문제를 미루는 대신 기록하고 나누어 보는 접근이 필요합니다.",
        "판단이 어려운 순간에는 빈도, 영향, 되돌릴 수 있는지를 함께 보면 됩니다.",
        "순서를 정하면 복잡한 문제도 오늘 할 수 있는 행동으로 바뀝니다.",
        "좋은 방식은 어렵기보다 반복 가능하고, 다음 행동이 분명하다는 특징이 있습니다.",
        "현실 사례에서는 말로 아는 것과 실제로 적용하는 것 사이의 차이가 드러납니다.",
        "한 번의 결심보다 매일 확인할 수 있는 작은 연결고리가 더 중요합니다.",
        "처음부터 완벽하게 하려 하지 말고, 지금 보이는 한 가지부터 바꾸는 것이 좋습니다.",
        "작은 실험은 부담을 줄이고, 결과를 확인하며 방식을 고칠 수 있게 합니다.",
        "점검 기준을 미리 정해두면 시간이 지나도 같은 실수를 줄일 수 있습니다.",
        "결국 핵심은 복잡한 문제를 생활 속에서 계속 실행 가능한 방식으로 바꾸는 것입니다.",
    ]
    narrations = [f"{narration} {details[index]}" for index, narration in enumerate(narrations)]
    scenes = []
    for index, narration in enumerate(narrations):
        scenes.append({
            "topic_id": topic["id"],
            "title": LAYOUT_TITLES[index],
            "title_en": LAYOUT_TITLES_EN[index],
            "caption": _first_sentence(narration),
            "narration": narration,
            "visual": (
                f"{topic['subject']}. Scene focus: {LAYOUT_TITLES_EN[index]}. "
                f"Represent this Korean narration literally and clearly: {narration} "
                "Show a clear visual situation that matches this exact scene, with relevant people, objects, and actions fully visible. "
                "Use a different composition from other scenes and keep the subject away from all edges. "
                "No text, no logos, no watermark."
            ),
            "provider": scene_image_provider(index),
        })
    return scenes


def build_scenes(topic):
    try:
        data = generate_narrations(topic)
        scenes = []
        for index, item in enumerate(data):
            title = item["title"]
            title_en = item.get("title_en") or LAYOUT_TITLES_EN[index]
            narration = item["narration"]
            scenes.append({
                "topic_id": topic["id"],
                "title": title,
                "title_en": title_en,
                "caption": _first_sentence(narration),
                "narration": narration,
                "visual": (
                    f"{topic['subject']}. Scene focus: {title_en}. "
                    f"Represent this Korean narration literally and clearly: {narration} "
                    "Show a clear visual situation that matches this exact scene, with relevant people, objects, and actions fully visible. "
                    "Use a different composition from other scenes and keep the subject away from all edges. "
                    "No text, no logos, no watermark."
                ),
                "provider": scene_image_provider(index),
            })
        return scenes
    except Exception as exc:
        print(f"AI narration generation failed; using fallback template: {exc}")
        return _build_scenes_fallback(topic)


def font(size):
    if _CJK_FONT_PATH:
        return ImageFont.truetype(_CJK_FONT_PATH, size=size, index=0)
    return ImageFont.load_default()


def generate_openai(prompt, path):
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=float(os.getenv("OPENAI_IMAGE_TIMEOUT", "180")))
    result = client.images.generate(
        model=os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1"),
        prompt=prompt,
        size=os.getenv("OPENAI_IMAGE_SIZE", "1536x1024"),
        quality=os.getenv("OPENAI_IMAGE_QUALITY", "medium"),
        n=1,
    )
    path.write_bytes(base64.b64decode(result.data[0].b64_json))


def generate_gemini(prompt, path):
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY") or os.environ["GOOGLE_API_KEY"])
    primary = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
    fallbacks = [m for m in [
        "gemini-2.5-flash-image",
        "nano-banana-pro-preview",
        "gemini-3.1-flash-image",
        "gemini-3-pro-image",
    ] if m != primary]
    errors = []
    for model in [primary] + fallbacks:
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
            )
            for part in response.candidates[0].content.parts:
                if getattr(part, "inline_data", None):
                    path.write_bytes(part.inline_data.data)
                    print(f"Gemini image generated with model: {model}")
                    return
            errors.append(f"{model}: no image data returned")
            print(f"Gemini model {model} returned no image; trying next")
        except Exception as exc:
            errors.append(f"{model}: {exc}")
            print(f"Gemini model {model} failed: {exc}; trying next")
    raise RuntimeError("All Gemini image models failed: " + " | ".join(errors))


def fit_cover(path):
    img = Image.open(path).convert("RGB")
    target = WIDTH / HEIGHT
    ratio = img.width / img.height
    if ratio > target:
        new_w = int(img.height * target)
        left = (img.width - new_w) // 2
        img = img.crop((left, 0, left + new_w, img.height))
    else:
        new_h = int(img.width / target)
        top = (img.height - new_h) // 2
        img = img.crop((0, top, img.width, top + new_h))
    return img.resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)


def resize_cover(img, size):
    target_w, target_h = size
    target = target_w / target_h
    ratio = img.width / img.height
    if ratio > target:
        new_w = int(img.height * target)
        left = (img.width - new_w) // 2
        img = img.crop((left, 0, left + new_w, img.height))
    else:
        new_h = int(img.width / target)
        top = (img.height - new_h) // 2
        img = img.crop((0, top, img.width, top + new_h))
    return img.resize(size, Image.Resampling.LANCZOS)


def resize_contain(img, size):
    target_w, target_h = size
    scale = min(target_w / img.width, target_h / img.height)
    new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
    return img.resize(new_size, Image.Resampling.LANCZOS)


def crop_dark_borders(img):
    gray = img.convert("L")
    mask = gray.point(lambda pixel: 255 if pixel > 18 else 0)
    bbox = mask.getbbox()
    if not bbox:
        return img
    left, top, right, bottom = bbox
    crop_w, crop_h = right - left, bottom - top
    has_border = left > 20 or top > 20 or right < img.width - 20 or bottom < img.height - 20
    enough_content = crop_w >= img.width * 0.45 and crop_h >= img.height * 0.45
    if not has_border or not enough_content:
        return img
    pad = 6
    return img.crop((
        max(0, left - pad),
        max(0, top - pad),
        min(img.width, right + pad),
        min(img.height, bottom + pad),
    ))


def slide_visual_rect(layout):
    if layout in {1, 4}:
        return (220, 160, 1700, 805)
    if layout == 2:
        return (140, 150, 1550, 820)
    if layout == 3:
        return (310, 145, 1610, 805)
    return (250, 150, 1780, 815)


def compose_slide_background(path, layout):
    src = crop_dark_borders(Image.open(path).convert("RGB"))
    base = resize_cover(src, (WIDTH, HEIGHT)).filter(ImageFilter.GaussianBlur(radius=30))
    base = Image.blend(base, Image.new("RGB", base.size, (5, 8, 14)), 0.35)

    left, top, right, bottom = slide_visual_rect(layout)
    visual_w, visual_h = right - left, bottom - top
    visual_bg = resize_cover(src, (visual_w, visual_h)).filter(ImageFilter.GaussianBlur(radius=22))
    visual_bg = Image.blend(visual_bg, Image.new("RGB", visual_bg.size, (5, 8, 14)), 0.15)
    base.paste(visual_bg, (left, top))

    contained = resize_contain(src, (visual_w, visual_h))
    x = left + (visual_w - contained.width) // 2
    y = top + (visual_h - contained.height) // 2
    base.paste(contained, (x, y))
    return base


def fit_background(path):
    src = Image.open(path).convert("RGB")
    bg = fit_cover(path).filter(ImageFilter.GaussianBlur(radius=28))
    bg = Image.blend(bg, Image.new("RGB", bg.size, (5, 8, 14)), 0.18)

    scale = min(WIDTH / src.width, HEIGHT / src.height)
    new_size = (int(src.width * scale), int(src.height * scale))
    contained = src.resize(new_size, Image.Resampling.LANCZOS)
    x = (WIDTH - contained.width) // 2
    y = (HEIGHT - contained.height) // 2
    bg.paste(contained, (x, y))
    return bg


def text_size(draw, text, fnt):
    box = draw.textbbox((0, 0), text, font=fnt)
    return box[2] - box[0], box[3] - box[1]


def draw_text_centered(draw, text, rect, fnt, fill):
    left, top, right, bottom = rect
    box = draw.textbbox((0, 0), text, font=fnt)
    width, height = box[2] - box[0], box[3] - box[1]
    x = left + ((right - left) - width) / 2 - box[0]
    y = top + ((bottom - top) - height) / 2 - box[1]
    draw.text((x, y), text, font=fnt, fill=fill)


def wrap_text(draw, text, fnt, max_width):
    lines, line = [], ""
    for ch in text:
        trial = line + ch
        width, _ = text_size(draw, trial, fnt)
        if width <= max_width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = ch
    if line:
        lines.append(line)
    return lines


def draw_wrapped(draw, text, xy, fnt, max_width, fill, spacing=12, align="left"):
    """Draw wrapped text and return the y coordinate after the last line."""
    x, y = xy
    lines = wrap_text(draw, text, fnt, max_width)
    for line in lines:
        width, height = text_size(draw, line, fnt)
        line_x = x + (max_width - width) / 2 if align == "center" else x
        draw.text((line_x, y), line, font=fnt, fill=fill)
        y += height + spacing
    return y


def draw_badge(draw, text, xy, fill=(255, 205, 77, 255), text_fill=(8, 10, 14, 255)):
    x, y = xy
    rect = (x, y, x + 266, y + 56)
    draw.rounded_rectangle(rect, radius=26, fill=fill)
    draw_text_centered(draw, text, rect, font(30), text_fill)


def draw_progress(draw, index, total, y=994, color=(255, 205, 77, 255)):
    x1, x2 = 72, 1848
    draw.line((x1, y, x2, y), fill=(255, 255, 255, 70), width=6)
    draw.line((x1, y, x1 + int((x2 - x1) * ((index + 1) / total)), y), fill=color, width=8)


def draw_panel_texture(draw, rect, accent, align="left"):
    left, top, right, bottom = rect
    for offset in range(0, int(bottom - top), 82):
        y = top + offset
        draw.line((left + 38, y, right - 38, y), fill=(255, 255, 255, 18), width=1)
    if align == "right":
        draw.rectangle((right - 14, top, right, bottom), fill=accent)
        for x in range(right - 120, right - 34, 28):
            draw.line((x, bottom - 190, x + 82, bottom - 108), fill=(*accent[:3], 70), width=3)
    else:
        draw.rectangle((left, top, left + 14, bottom), fill=accent)
        for x in range(left + 36, left + 122, 28):
            draw.line((x, bottom - 190, x + 82, bottom - 108), fill=(*accent[:3], 70), width=3)


def draw_scene_number(draw, index, xy, fill=(255, 255, 255, 32)):
    draw.text(xy, f"{index + 1:02}", font=font(168), fill=fill)


def draw_caption_box(draw, caption, xy, max_width, accent, align="left"):
    x, y = xy
    marker = (x, y + 8, x + 8, y + 102)
    if align == "center":
        marker = (x + max_width // 2 - 4, y - 18, x + max_width // 2 + 4, y + 2)
    draw.rounded_rectangle(marker, radius=4, fill=accent)
    return draw_wrapped(draw, caption, (x + (24 if align != "center" else 0), y), font(35), max_width - 30, (218, 231, 244, 255), 12, align=align)


def draw_footer_meta(draw, index, total, y, accent):
    label = f"{index + 1:02} / {total:02}"
    draw.text((72, y - 42), label, font=font(28), fill=(230, 238, 248, 180))
    draw_progress(draw, index, total, y=y, color=accent)


def draw_burned_subtitle(draw, text):
    if not text:
        return
    fnt = font(38)
    max_width = 1460
    lines = wrap_text(draw, text, fnt, max_width)
    lines = lines[:2]
    if not lines:
        return
    line_sizes = [text_size(draw, line, fnt) for line in lines]
    text_h = sum(h for _, h in line_sizes) + max(0, len(lines) - 1) * 12
    pad_x, pad_y = 34, 22
    box_w = min(1620, max(w for w, _ in line_sizes) + pad_x * 2)
    box_h = text_h + pad_y * 2
    left = (WIDTH - box_w) // 2
    top = 850
    rect = (left, top, left + box_w, top + box_h)
    draw.rounded_rectangle(rect, radius=18, fill=(0, 0, 0, 190))
    y = top + pad_y
    for line, (line_w, line_h) in zip(lines, line_sizes):
        x = left + (box_w - line_w) / 2
        draw.text((x + 2, y + 2), line, font=fnt, fill=(0, 0, 0, 170))
        draw.text((x, y), line, font=fnt, fill=(255, 255, 255, 255))
        y += line_h + 12


def _safe_text(scene, key):
    """Return Korean text if CJK font is available, otherwise English fallback or empty string."""
    text = scene.get(key, "")
    if _has_korean(text) and not _CJK_FONT_PATH:
        if key == "title":
            return scene.get("title_en", "")
        return ""
    return text


def normalize_overlay_text(text):
    text = re.sub(r"\s+", "", text or "")
    return re.sub(r"[^0-9A-Za-z가-힣]", "", text).lower()


def should_show_caption(title, caption):
    title_norm = normalize_overlay_text(title)
    caption_norm = normalize_overlay_text(caption)
    if not caption_norm:
        return False
    if title_norm and (caption_norm.startswith(title_norm) or title_norm in caption_norm):
        return False
    return True


def safe_asset_name(text):
    text = str(text or "")
    text = re.sub(r"[^0-9A-Za-z_-]+", "-", text or "").strip("-").lower()
    return text or "topic"


def prompt_cache_key(scene, prompt):
    payload = "|".join(
        str(part or "")
        for part in [
            scene.get("topic_id", ""),
            scene.get("title_en", ""),
            scene.get("visual", ""),
            prompt,
        ]
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]


def draw_scene_overlay(draw, scene, index, total):
    badge_text = f"SCENE {index + 1:02}"
    title = _safe_text(scene, "title")
    WHITE = (255, 255, 255, 255)
    BG = (5, 8, 14)          # panel base colour
    layout = index % 5
    accents = [
        (255, 205, 77, 255),
        (104, 211, 145, 255),
        (125, 211, 252, 255),
        (248, 113, 113, 255),
        (250, 204, 21, 255),
    ]
    accent = accents[layout]
    draw.rectangle((0, 0, WIDTH, HEIGHT), fill=(*BG, 92))
    draw.rounded_rectangle((56, 42, 1864, 132), radius=18, fill=(*BG, 218))
    draw.rectangle((56, 42, 1864, 50), fill=accent)
    draw_badge(draw, badge_text, (86, 60), fill=accent)
    draw_wrapped(draw, title, (390, 62), font(52), 1220, WHITE, 8)
    draw.text((1718, 63), f"{index + 1:02}", font=font(48), fill=(230, 238, 248, 145))

    left, top, right, bottom = slide_visual_rect(layout)
    draw.rounded_rectangle((left - 8, top - 8, right + 8, bottom + 8), radius=20, outline=(*accent[:3], 210), width=4)
    draw_footer_meta(draw, index, total, 1038, accent)


def render_scene_image(scene, index, total, raw_dir, frame_dir):
    frame = frame_dir / f"scene-{index + 1:02}.jpg"
    prompt = (
        "Realistic cinematic Korean YouTube documentary still, 16:9. "
        "Create one clear, topic-specific scene that directly matches the narration and slide title. "
        "The main person, clothing, object, or situation must be fully visible within the frame with comfortable margins. "
        "Use a balanced composition with meaningful details across the whole image; do not leave an empty half of the frame. "
        "Avoid extreme close-ups, cropped heads, cropped hands, cropped objects, backs-only shots, or subjects pushed to the edge. "
        "STRICT RULE: absolutely zero text, zero letters, zero numbers, zero signs, zero labels, "
        "zero captions, zero subtitles, zero watermarks, zero logos anywhere in the image. "
        "Do not render any written language, Hangul, English letters, numbers, symbols, UI text, signs, labels, subtitles, logos, or watermark. "
        "Avoid books, papers, screens, posters, whiteboards, or signboards with visible writing. "
        "If text-like detail would be needed, replace it with clean abstract shapes, blank surfaces, or non-readable visual metaphors. "
        f"{scene['visual']} Narration context: {scene['narration']}"
    )
    topic_id = safe_asset_name(scene.get("topic_id", "topic"))
    cache_key = prompt_cache_key(scene, prompt)
    raw = raw_dir / f"{topic_id}-scene-{index + 1:02}-{scene['provider']}-{cache_key}.png"
    if raw.exists() and raw.stat().st_size == 0:
        raw.unlink()
    if not raw.exists():
        if scene["provider"] == "openai":
            generate_openai(prompt, raw)
        else:
            generate_gemini(prompt, raw)
    img = compose_slide_background(raw, index % 5).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw_scene_overlay(draw, scene, index, total)
    if BURN_IN_SUBTITLES:
        draw_burned_subtitle(draw, _safe_text(scene, "caption"))
    Image.alpha_composite(img, overlay).convert("RGB").save(frame, quality=94)
    return frame


def render_scene_images(scenes, raw_dir, frame_dir):
    total = len(scenes)
    workers = SCENE_IMAGE_MAX_WORKERS
    if workers > 1:
        try:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(render_scene_image, scene, idx, total, raw_dir, frame_dir): idx
                    for idx, scene in enumerate(scenes)
                }
                for future in as_completed(futures):
                    idx = futures[future]
                    future.result()
                    print(f"Scene {idx + 1:02} image complete")
            return
        except Exception as exc:
            print(f"Parallel scene image generation failed; retrying serially: {exc}")

    for idx, scene in enumerate(scenes):
        render_scene_image(scene, idx, total, raw_dir, frame_dir)
        print(f"Scene {idx + 1:02} image complete")


def tts_voice_ids():
    voice_ids = [os.environ["ELEVENLABS_VOICE_ID"]]
    if os.getenv("ELEVENLABS_ALLOW_FALLBACK", "false").lower() == "true":
        fallback = os.getenv("ELEVENLABS_FALLBACK_VOICE_IDS", "")
        voice_ids.extend(x.strip() for x in fallback.split(",") if x.strip())
    return list(dict.fromkeys(voice_ids))


def elevenlabs_tts_with_voice(text, path, voice_id):
    payload_data = {
        "text": text,
        "model_id": os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2"),
        "voice_settings": {
            "stability": float(os.getenv("ELEVENLABS_STABILITY", "0.70")),
            "similarity_boost": float(os.getenv("ELEVENLABS_SIMILARITY", "0.84")),
            "style": float(os.getenv("ELEVENLABS_STYLE", "0.0")),
            "use_speaker_boost": os.getenv("ELEVENLABS_SPEAKER_BOOST", "true").lower() != "false",
            "speed": float(os.getenv("ELEVENLABS_SPEED", "0.94")),
        },
        "apply_text_normalization": os.getenv("ELEVENLABS_TEXT_NORMALIZATION", "on"),
    }
    seed = os.getenv("ELEVENLABS_SEED")
    if seed:
        payload_data["seed"] = int(seed)
    payload = json.dumps(payload_data).encode("utf-8")
    req = request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        data=payload,
        headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"], "Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=180) as response:
        path.write_bytes(response.read())


def macos_say_tts(text, path):
    if not shutil.which("say"):
        raise RuntimeError("macOS say command is not available")
    aiff = path.with_suffix(".aiff")
    subprocess.run(["say", "-o", str(aiff), text], check=True)
    subprocess.run(["ffmpeg", "-y", "-i", str(aiff), "-codec:a", "libmp3lame", "-b:a", "128k", str(path)], check=True)
    aiff.unlink(missing_ok=True)


def synthesize_tts(text, path):
    errors = []
    for voice_id in tts_voice_ids():
        try:
            elevenlabs_tts_with_voice(text, path, voice_id)
            print(f"TTS complete with ElevenLabs voice: {voice_id}")
            return
        except Exception as exc:
            errors.append(f"{voice_id}: {exc}")
            print(f"ElevenLabs TTS failed for voice {voice_id}: {exc}")
    try:
        macos_say_tts(text, path)
        print("TTS complete with macOS say fallback")
        return
    except Exception as exc:
        errors.append(f"macOS say: {exc}")
    raise RuntimeError("All TTS providers failed: " + " | ".join(errors))


def normalize_narration_text(text):
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([.,!?])", r"\1", text)
    return text


def transcode_narration_audio(source, target):
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=8,aresample=48000",
            "-ar",
            "48000",
            "-ac",
            "1",
            str(target),
        ],
        check=True,
    )


def synthesize_scene_narrations(scenes, out_dir):
    scene_wavs = []
    scene_durations = []
    for idx, scene in enumerate(scenes, 1):
        scene_text = normalize_narration_text(scene["narration"])
        scene_mp3 = out_dir / f"scene-{idx:02}-tts.mp3"
        scene_wav = out_dir / f"scene-{idx:02}-tts.wav"
        synthesize_tts(scene_text, scene_mp3)
        transcode_narration_audio(scene_mp3, scene_wav)
        scene_wavs.append(scene_wav)
        scene_durations.append(duration(scene_wav))
        print(f"TTS scene {idx:02} complete")
    return scene_wavs, scene_durations


def concat_audio_files(audio_files, concat_path, output_path):
    concat_path.write_text(
        "\n".join(f"file '{path.resolve()}'" for path in audio_files),
        encoding="utf-8",
    )
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_path), "-c", "copy", str(output_path)],
        check=True,
    )


def duration(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def video_probe(path):
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,bit_rate",
            "-show_entries",
            "stream=codec_type,width,height,bit_rate",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def validate_video_quality(path, expected_duration=None, min_width=1280, min_height=720):
    if not path.exists() or path.stat().st_size < 100_000:
        raise RuntimeError(f"Video is missing or too small: {path}")
    probe = video_probe(path)
    streams = probe.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    if not video_streams:
        raise RuntimeError("Video has no video stream")
    if not audio_streams:
        raise RuntimeError("Video has no audio stream")
    width = int(video_streams[0].get("width") or 0)
    height = int(video_streams[0].get("height") or 0)
    if width < min_width or height < min_height:
        raise RuntimeError(f"Video resolution is too low: {width}x{height}")
    actual_duration = float(probe.get("format", {}).get("duration") or 0)
    if actual_duration <= 0:
        raise RuntimeError("Video duration is empty")
    if expected_duration and not (expected_duration * 0.65 <= actual_duration <= expected_duration * 1.45):
        raise RuntimeError(
            f"Video duration mismatch: expected about {expected_duration:.1f}s, got {actual_duration:.1f}s"
        )
    return actual_duration


def _find_key(data, key):
    if isinstance(data, dict):
        if key in data:
            return data[key]
        for value in data.values():
            found = _find_key(value, key)
            if found is not None:
                return found
    if isinstance(data, list):
        for value in data:
            found = _find_key(value, key)
            if found is not None:
                return found
    return None


def heygen_headers(content_type="application/json"):
    api_key = os.getenv("HEYGEN_API_KEY")
    if not api_key:
        raise RuntimeError("HEYGEN_API_KEY is not set")
    headers = {"x-api-key": api_key}
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def heygen_json(method, path, payload=None, timeout=180):
    body = None
    headers = heygen_headers()
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    req = request.Request(f"{HEYGEN_BASE_URL}{path}", data=body, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HeyGen API failed with HTTP {exc.code}: {detail}") from exc


def heygen_upload_asset(path):
    boundary = f"----codex-heygen-{int(time.time() * 1000)}"
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    file_bytes = path.read_bytes()
    body = b"".join(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            (
                f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8"),
            file_bytes,
            b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    req = request.Request(
        f"{HEYGEN_BASE_URL}/v3/assets",
        data=body,
        headers=heygen_headers(f"multipart/form-data; boundary={boundary}"),
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=300) as response:
            data = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HeyGen asset upload failed with HTTP {exc.code}: {detail}") from exc
    asset_id = _find_key(data, "asset_id") or _find_key(data, "id")
    if not asset_id:
        raise RuntimeError(f"HeyGen asset upload did not return an asset id: {data}")
    return asset_id


def heygen_poll_video(video_id):
    deadline = time.time() + HEYGEN_POLL_TIMEOUT
    while time.time() < deadline:
        data = heygen_json("GET", f"/v3/videos/{video_id}", timeout=60)
        status = _find_key(data, "status")
        if status == "completed":
            video_url = _find_key(data, "video_url") or _find_key(data, "url")
            if not video_url:
                raise RuntimeError(f"HeyGen completed without a video URL: {data}")
            return video_url
        if status == "failed":
            message = _find_key(data, "failure_message") or _find_key(data, "message") or data
            raise RuntimeError(f"HeyGen video generation failed: {message}")
        time.sleep(HEYGEN_POLL_INTERVAL)
    raise RuntimeError(f"HeyGen video generation timed out for {video_id}")


def download_url(url, target):
    with request.urlopen(url, timeout=300) as response:
        target.write_bytes(response.read())


def parse_scene_indices(value):
    indices = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        indices.add(int(part))
    return indices


def srt_time(seconds):
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def write_srt(scenes, scene_durations, path):
    now = 0.0
    blocks = []
    for idx, (scene, dur) in enumerate(zip(scenes, scene_durations), 1):
        blocks.append(f"{idx}\n{srt_time(now)} --> {srt_time(now + dur)}\n{scene['caption']}\n")
        now += dur
    path.write_text("\n".join(blocks), encoding="utf-8")


def render_slide_motion_clip(frame, duration_seconds, target, index):
    frames = max(1, int(round(duration_seconds * FPS)))
    if index % 2 == 0:
        x_expr = f"(iw-iw/zoom)*on/{frames}"
    else:
        x_expr = f"(iw-iw/zoom)*(1-on/{frames})"
    vf = (
        "scale=2200:-1,"
        f"zoompan=z='min(zoom+0.00042,1.045)':x='{x_expr}':"
        f"y='ih/2-(ih/zoom/2)':d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS},"
        "setsar=1,format=yuv420p"
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-i",
            str(frame),
            "-vf",
            vf,
            "-frames:v",
            str(frames),
            "-r",
            str(FPS),
            "-c:v",
            "libx264",
            "-crf",
            "19",
            "-pix_fmt",
            "yuv420p",
            str(target),
        ],
        check=True,
    )


def render_slideshow_video(scene_durations, wav_audio, frame_dir):
    total = sum(scene_durations)
    concat = OUT / "concat.txt"
    silent = OUT / "silent.mp4"
    bgm = OUT / "bgm.wav"
    mixed = OUT / "mixed.m4a"
    video = OUT / "final.mp4"
    if SLIDE_MOTION_ENABLED:
        clip_dir = OUT / "slide_clips"
        clip_dir.mkdir(exist_ok=True)
        clips = []
        for idx, dur in enumerate(scene_durations):
            clip = clip_dir / f"scene-{idx + 1:02}.mp4"
            render_slide_motion_clip(frame_dir / f"scene-{idx + 1:02}.jpg", dur, clip, idx)
            clips.append(clip)
        concat.write_text("\n".join(f"file '{clip.resolve()}'" for clip in clips), encoding="utf-8")
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(silent)], check=True)
    else:
        lines = []
        for idx, dur in enumerate(scene_durations):
            lines += [f"file '{frame_dir / f'scene-{idx + 1:02}.jpg'}'", f"duration {dur:.3f}"]
        lines.append(f"file '{frame_dir / f'scene-{len(scene_durations):02}.jpg'}'")
        concat.write_text("\n".join(lines), encoding="utf-8")
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-vf", f"scale={WIDTH}:{HEIGHT},format=yuv420p", "-r", str(FPS), "-c:v", "libx264", "-crf", "19", str(silent)], check=True)
    if BGM_ENABLED:
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=82:sample_rate=48000:duration={total + 1}", "-filter_complex", "volume=0.010", str(bgm)], check=True)
        subprocess.run(["ffmpeg", "-y", "-i", str(wav_audio), "-i", str(bgm), "-filter_complex", "[0:a]volume=1.0[a0];[1:a]volume=0.03[a1];[a0][a1]amix=inputs=2:duration=first", "-c:a", "aac", "-b:a", "192k", str(mixed)], check=True)
    else:
        subprocess.run(["ffmpeg", "-y", "-i", str(wav_audio), "-c:a", "aac", "-b:a", "192k", str(mixed)], check=True)
    subprocess.run(["ffmpeg", "-y", "-i", str(silent), "-i", str(mixed), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-shortest", str(video)], check=True)
    return video


def render_local_scene_clip(frame, audio, duration_seconds, target):
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-t",
            f"{duration_seconds:.3f}",
            "-i",
            str(frame),
            "-i",
            str(audio),
            "-vf",
            f"scale={WIDTH}:{HEIGHT},format=yuv420p",
            "-r",
            str(FPS),
            "-c:v",
            "libx264",
            "-crf",
            "19",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            str(target),
        ],
        check=True,
    )


def transcode_scene_clip(source, target):
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-vf",
            f"scale={WIDTH}:{HEIGHT},fps={FPS},format=yuv420p",
            "-c:v",
            "libx264",
            "-crf",
            "19",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            str(target),
        ],
        check=True,
    )


def render_heygen_scene(scene, index, frame, audio, expected_duration, out_dir):
    raw_video = out_dir / f"scene-{index:02}-heygen-raw.mp4"
    normalized = out_dir / f"scene-{index:02}-heygen.mp4"
    if normalized.exists():
        validate_video_quality(normalized, expected_duration)
        return normalized

    image_asset_id = heygen_upload_asset(frame)
    audio_asset_id = heygen_upload_asset(audio)
    payload = {
        "type": "image",
        "image": {"type": "asset_id", "asset_id": image_asset_id},
        "audio_asset_id": audio_asset_id,
        "title": f"{scene['title_en']} scene {index:02}",
        "resolution": HEYGEN_RESOLUTION,
        "aspect_ratio": HEYGEN_ASPECT_RATIO,
    }
    data = heygen_json("POST", "/v3/videos", payload=payload, timeout=180)
    video_id = _find_key(data, "video_id") or _find_key(data, "id")
    if not video_id:
        raise RuntimeError(f"HeyGen video creation did not return a video id: {data}")
    video_url = heygen_poll_video(video_id)
    download_url(video_url, raw_video)
    validate_video_quality(raw_video, expected_duration)
    transcode_scene_clip(raw_video, normalized)
    validate_video_quality(normalized, expected_duration)
    return normalized


def apply_bgm_to_video(source, target, total_duration):
    if not BGM_ENABLED:
        if source != target:
            shutil.copyfile(source, target)
        return
    bgm = OUT / "heygen_hybrid_bgm.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=82:sample_rate=48000:duration={total_duration + 1}",
            "-filter_complex",
            "volume=0.010",
            str(bgm),
        ],
        check=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-i",
            str(bgm),
            "-filter_complex",
            "[0:a]volume=1.0[a0];[1:a]volume=0.03[a1];[a0][a1]amix=inputs=2:duration=first[a]",
            "-map",
            "0:v:0",
            "-map",
            "[a]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            str(target),
        ],
        check=True,
    )


def render_heygen_hybrid_video(scenes, scene_wavs, scene_durations, frame_dir):
    if not HEYGEN_ENABLED:
        raise RuntimeError("HeyGen is disabled")
    target_indices = parse_scene_indices(HEYGEN_SCENE_INDICES)
    if not target_indices:
        raise RuntimeError("HEYGEN_SCENE_INDICES is empty")

    clip_dir = OUT / "heygen_clips"
    clip_dir.mkdir(exist_ok=True)
    concat = OUT / "heygen_concat.txt"
    clips = []
    replaced = 0
    for idx, (scene, wav, dur) in enumerate(zip(scenes, scene_wavs, scene_durations), 1):
        frame = frame_dir / f"scene-{idx:02}.jpg"
        if idx in target_indices:
            try:
                clip = render_heygen_scene(scene, idx, frame, wav, dur, clip_dir)
                replaced += 1
                print(f"HeyGen scene {idx:02} accepted")
            except Exception as exc:
                print(f"HeyGen scene {idx:02} rejected; using original slide scene: {exc}")
                clip = clip_dir / f"scene-{idx:02}-local.mp4"
                render_local_scene_clip(frame, wav, dur, clip)
        else:
            clip = clip_dir / f"scene-{idx:02}-local.mp4"
            if not clip.exists():
                render_local_scene_clip(frame, wav, dur, clip)
        clips.append(clip)

    if replaced < HEYGEN_MIN_REPLACED_SCENES:
        raise RuntimeError(f"Only {replaced} HeyGen scenes passed; required {HEYGEN_MIN_REPLACED_SCENES}")

    concat.write_text("\n".join(f"file '{path.resolve()}'" for path in clips), encoding="utf-8")
    without_bgm = OUT / "heygen_hybrid_no_bgm.mp4"
    video = OUT / "final.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(without_bgm)],
        check=True,
    )
    apply_bgm_to_video(without_bgm, video, sum(scene_durations))
    validate_video_quality(video, sum(scene_durations), min_width=WIDTH, min_height=HEIGHT)
    return video


def render_video(topic, scenes):
    OUT.mkdir(parents=True, exist_ok=True)
    raw_dir, frame_dir = OUT / "raw", OUT / "frames"
    raw_dir.mkdir(exist_ok=True)
    frame_dir.mkdir(exist_ok=True)

    wav_audio = OUT / "narration.wav"
    audio_concat = OUT / "audio_concat.txt"
    scene_wavs, scene_durations = synthesize_scene_narrations(scenes, OUT)
    concat_audio_files(scene_wavs, audio_concat, wav_audio)

    render_scene_images(scenes, raw_dir, frame_dir)

    srt = OUT / "subtitles.srt"
    write_srt(scenes, scene_durations, srt)

    if HEYGEN_ENABLED:
        try:
            return render_heygen_hybrid_video(scenes, scene_wavs, scene_durations, frame_dir), srt
        except Exception as exc:
            print(f"HeyGen hybrid render was not accepted; falling back to original renderer: {exc}")

    return render_slideshow_video(scene_durations, wav_audio, frame_dir), srt


def youtube_service():
    creds = Credentials.from_authorized_user_file("token.json", ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.force-ssl"])
    return build("youtube", "v3", credentials=creds)


def upload(topic, video, srt):
    service = youtube_service()
    body = {
        "snippet": {
            "title": topic["title"],
            "description": topic["description"],
            "tags": topic["tags"],
            "categoryId": "27",
            "defaultLanguage": "ko",
            "defaultAudioLanguage": "ko",
        },
        "status": {"privacyStatus": os.getenv("YOUTUBE_PRIVACY", "private"), "selfDeclaredMadeForKids": False},
    }
    req = service.videos().insert(part="snippet,status", body=body, media_body=MediaFileUpload(str(video), chunksize=-1, resumable=True))
    response = None
    while response is None:
        _, response = req.next_chunk()
    video_id = response["id"]
    if UPLOAD_YOUTUBE_CAPTIONS:
        service.captions().insert(
            part="snippet",
            body={"snippet": {"videoId": video_id, "language": "ko", "name": "Korean", "isDraft": False}},
            media_body=MediaFileUpload(str(srt), mimetype="application/x-subrip"),
        ).execute()
    print(f"Uploaded: https://www.youtube.com/watch?v={video_id}")
    return video_id


def main():
    history = load_history()
    topic = pick_topic(history)
    scenes = build_scenes(topic)
    video, srt = render_video(topic, scenes)
    video_duration = duration(video)
    if not 180 <= video_duration <= 480:
        raise RuntimeError(f"Generated video duration is outside 3-8 minutes: {video_duration:.1f}s")
    video_id = upload(topic, video, srt)
    history.append({
        "category": TOPIC_CATEGORY,
        "topic": topic["topic"],
        "title": topic["title"],
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "automated": True,
        "video_id": video_id,
        "voice_id": os.getenv("ELEVENLABS_VOICE_ID"),
    })
    save_history(history)


if __name__ == "__main__":
    main()
