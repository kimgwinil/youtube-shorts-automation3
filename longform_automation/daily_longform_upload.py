import base64
import json
import os
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib import request

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont


ROOT = Path.cwd()
HISTORY = Path(__file__).with_name("topic-history.json")
OUT = ROOT / "output" / datetime.now().strftime("%Y%m%d")
WIDTH, HEIGHT, FPS = 1920, 1080, 30
SCENE_IMAGE_MAX_WORKERS = max(1, min(6, int(os.getenv("SCENE_IMAGE_MAX_WORKERS", "4"))))

TOPICS = [
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
            "Fields required: id, topic, title, description, tags, subject, problem, solution, example. "
            "description must include two short paragraphs and 5 Korean hashtags. "
            "tags must be a list of 5 to 7 Korean strings. "
            "subject must be an English visual prompt for realistic Korean documentary imagery. "
            "problem, solution, and example must be concise Korean phrases. "
            "example must describe a concrete Korean real-life situation and must not include English.\n\n"
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
        "- '구조로 나눠보겠습니다', '첫 번째 원인은', '마지막 점검은 세 가지입니다' 같은\n"
        "  고정 표현을 절대 사용하지 말 것 — 매 영상이 같은 패턴처럼 들리면 안 됩니다\n"
        "- 각 나레이션은 2~3문장, 자연스럽고 생동감 있는 한국어로 작성\n"
        "- 장면 제목도 주제에 어울리게 구체적으로 작성\n\n"
        "아래 JSON 배열 형식으로만 응답 (마크다운 코드블록 금지):\n"
        '[{"title": "한국어 장면 제목", "title_en": "English scene title", '
        '"narration": "나레이션 전문"}, ...]\n\n'
        "17개 장면 역할 (순서 고정, 제목은 자유롭게):\n"
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
    scenes = []
    for index, narration in enumerate(narrations):
        scenes.append({
            "title": LAYOUT_TITLES[index],
            "title_en": LAYOUT_TITLES_EN[index],
            "caption": narration.split(".")[0].strip() + ".",
            "narration": narration,
            "visual": f"{topic['subject']}. Scene focus: {LAYOUT_TITLES_EN[index]}. No text, no logos, no watermark.",
            "provider": "openai" if index % 2 == 0 else "gemini",
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
                "title": title,
                "title_en": title_en,
                "caption": narration.split(".")[0].strip() + ".",
                "narration": narration,
                "visual": f"{topic['subject']}. Scene focus: {title_en}. No text, no logos, no watermark.",
                "provider": "openai" if index % 2 == 0 else "gemini",
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
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
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


def fit_background(path):
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


def draw_wrapped(draw, text, xy, fnt, max_width, fill, spacing=12):
    x, y = xy
    lines, line = [], ""
    for ch in text:
        trial = line + ch
        box = draw.textbbox((0, 0), trial, font=fnt)
        if box[2] - box[0] <= max_width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = ch
    if line:
        lines.append(line)
    for line in lines:
        draw.text((x, y), line, font=fnt, fill=fill)
        box = draw.textbbox((0, 0), line, font=fnt)
        y += box[3] - box[1] + spacing


def draw_badge(draw, text, xy, fill=(255, 205, 77, 255), text_fill=(8, 10, 14, 255)):
    x, y = xy
    draw.rounded_rectangle((x, y, x + 266, y + 62), radius=28, fill=fill)
    draw.text((x + 30, y + 18), text, font=font(30), fill=text_fill)


def draw_progress(draw, index, total, y=994, color=(255, 205, 77, 255)):
    x1, x2 = 72, 1848
    draw.line((x1, y, x2, y), fill=(255, 255, 255, 70), width=6)
    draw.line((x1, y, x1 + int((x2 - x1) * ((index + 1) / total)), y), fill=color, width=8)


def _safe_text(scene, key):
    """Return Korean text if CJK font is available, otherwise English fallback or empty string."""
    text = scene.get(key, "")
    if _has_korean(text) and not _CJK_FONT_PATH:
        if key == "title":
            return scene.get("title_en", "")
        return ""
    return text


def draw_scene_overlay(draw, scene, index, total):
    badge_text = f"SCENE {index + 1:02}"
    title = _safe_text(scene, "title")
    caption = _safe_text(scene, "caption")
    layout = index % 5

    if layout == 0:
        draw.rectangle((0, 0, 930, HEIGHT), fill=(5, 8, 14, 188))
        draw_badge(draw, badge_text, (72, 70))
        draw_wrapped(draw, title, (72, 210), font(70), 760, (255, 255, 255, 255), 16)
        if caption:
            draw_wrapped(draw, caption, (72, 420), font(39), 760, (230, 236, 246, 255), 13)
        draw_progress(draw, index, total)
        return

    if layout == 1:
        draw.rectangle((0, 610, WIDTH, HEIGHT), fill=(5, 8, 14, 202))
        draw_badge(draw, badge_text, (72, 560), fill=(104, 211, 145, 255))
        draw_wrapped(draw, title, (72, 680), font(66), 1180, (255, 255, 255, 255), 14)
        if caption:
            draw_wrapped(draw, caption, (72, 825), font(38), 1500, (235, 241, 245, 255), 12)
        draw_progress(draw, index, total, y=1010, color=(104, 211, 145, 255))
        return

    if layout == 2:
        draw.rectangle((990, 0, WIDTH, HEIGHT), fill=(5, 8, 14, 190))
        draw_badge(draw, badge_text, (1088, 70), fill=(125, 211, 252, 255))
        draw_wrapped(draw, title, (1088, 210), font(66), 700, (255, 255, 255, 255), 16)
        if caption:
            draw_wrapped(draw, caption, (1088, 430), font(38), 700, (232, 240, 245, 255), 13)
        draw_progress(draw, index, total, color=(125, 211, 252, 255))
        return

    if layout == 3:
        draw.rectangle((0, 0, WIDTH, HEIGHT), fill=(4, 7, 12, 116))
        draw.rounded_rectangle((260, 190, 1660, 760), radius=34, fill=(5, 8, 14, 184))
        draw_badge(draw, badge_text, (827, 240), fill=(248, 113, 113, 255))
        draw_wrapped(draw, title, (360, 350), font(72), 1200, (255, 255, 255, 255), 18)
        if caption:
            draw_wrapped(draw, caption, (360, 560), font(38), 1200, (238, 242, 247, 255), 12)
        draw_progress(draw, index, total, color=(248, 113, 113, 255))
        return

    draw.rectangle((0, 0, WIDTH, 330), fill=(5, 8, 14, 205))
    draw.rectangle((0, 850, WIDTH, HEIGHT), fill=(5, 8, 14, 176))
    draw_badge(draw, badge_text, (72, 58), fill=(250, 204, 21, 255))
    draw_wrapped(draw, title, (380, 62), font(62), 1320, (255, 255, 255, 255), 14)
    if caption:
        draw_wrapped(draw, caption, (72, 888), font(40), 1500, (239, 244, 248, 255), 12)
    draw_progress(draw, index, total, y=1020, color=(250, 204, 21, 255))


def render_scene_image(scene, index, total, raw_dir, frame_dir):
    raw = raw_dir / f"scene-{index + 1:02}-{scene['provider']}.png"
    frame = frame_dir / f"scene-{index + 1:02}.jpg"
    prompt = (
        "Realistic cinematic Korean YouTube documentary still, no text, no logos, no watermark, 16:9. "
        "Leave clean negative space for editorial title overlays. "
        f"{scene['visual']} Narration context: {scene['narration']}"
    )
    if raw.exists() and raw.stat().st_size == 0:
        raw.unlink()
    if not raw.exists():
        if scene["provider"] == "openai":
            generate_openai(prompt, raw)
        else:
            generate_gemini(prompt, raw)
    img = fit_background(raw).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw_scene_overlay(draw, scene, index, total)
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
    fallback = os.getenv("ELEVENLABS_FALLBACK_VOICE_IDS", "")
    voice_ids.extend(x.strip() for x in fallback.split(",") if x.strip())
    return list(dict.fromkeys(voice_ids))


def elevenlabs_tts_with_voice(text, path, voice_id):
    payload = json.dumps({
        "text": text,
        "model_id": os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2"),
        "voice_settings": {
            "stability": float(os.getenv("ELEVENLABS_STABILITY", "0.70")),
            "similarity_boost": float(os.getenv("ELEVENLABS_SIMILARITY", "0.84")),
            "style": float(os.getenv("ELEVENLABS_STYLE", "0.0")),
            "use_speaker_boost": os.getenv("ELEVENLABS_SPEAKER_BOOST", "true").lower() != "false",
            "speed": float(os.getenv("ELEVENLABS_SPEED", "0.94")),
        },
    }).encode("utf-8")
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


def duration(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def srt_time(seconds):
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def render_video(topic, scenes):
    OUT.mkdir(parents=True, exist_ok=True)
    raw_dir, frame_dir = OUT / "raw", OUT / "frames"
    raw_dir.mkdir(exist_ok=True)
    frame_dir.mkdir(exist_ok=True)

    # Generate TTS per scene so each gets fresh voice energy (not one long concatenated request)
    scene_wav_files = []
    scene_durations = []
    for idx, scene in enumerate(scenes):
        scene_mp3 = OUT / f"scene-{idx + 1:02}-tts.mp3"
        scene_wav = OUT / f"scene-{idx + 1:02}-tts.wav"
        if not scene_mp3.exists() or scene_mp3.stat().st_size == 0:
            synthesize_tts(scene["narration"], scene_mp3)
            print(f"TTS scene {idx + 1:02} complete")
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(scene_mp3), "-ar", "48000", "-ac", "2", str(scene_wav)],
            check=True, capture_output=True,
        )
        scene_durations.append(duration(scene_wav))
        scene_wav_files.append(scene_wav)

    # Concatenate all scene wavs into one narration track
    wav_audio = OUT / "narration.wav"
    audio_list = OUT / "audio_concat.txt"
    audio_list.write_text(
        "\n".join(f"file '{w.name}'" for w in scene_wav_files), encoding="utf-8"
    )
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(audio_list), str(wav_audio)],
        check=True, capture_output=True,
    )
    total = sum(scene_durations)

    render_scene_images(scenes, raw_dir, frame_dir)

    concat = OUT / "concat.txt"
    lines = []
    for idx, dur in enumerate(scene_durations):
        lines += [f"file 'frames/scene-{idx + 1:02}.jpg'", f"duration {dur:.3f}"]
    lines.append(f"file 'frames/scene-{len(scenes):02}.jpg'")
    concat.write_text("\n".join(lines), encoding="utf-8")

    srt = OUT / "subtitles.srt"
    now = 0.0
    blocks = []
    for idx, (scene, dur) in enumerate(zip(scenes, scene_durations), 1):
        blocks.append(f"{idx}\n{srt_time(now)} --> {srt_time(now + dur)}\n{scene['caption']}\n")
        now += dur
    srt.write_text("\n".join(blocks), encoding="utf-8")

    silent = OUT / "silent.mp4"
    mixed = OUT / "mixed.m4a"
    video = OUT / "final.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-vf", f"scale={WIDTH}:{HEIGHT},format=yuv420p", "-r", str(FPS), "-c:v", "libx264", "-crf", "19", str(silent)], check=True)
    subprocess.run(["ffmpeg", "-y", "-i", str(wav_audio), "-filter_complex", "[0:a]volume=2.5[a0]", "-map", "0:v?", "-map", "[a0]", "-c:a", "aac", "-b:a", "192k", str(mixed)], check=True)
    subprocess.run(["ffmpeg", "-y", "-i", str(silent), "-i", str(mixed), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-shortest", str(video)], check=True)
    return video, srt


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
