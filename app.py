import json
import re
import base64
import random
import time
import os
import tempfile
import urllib.parse
import urllib.request
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
import streamlit as st
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from gtts import gTTS

try:
    from moviepy import ImageClip, AudioFileClip, VideoFileClip, concatenate_videoclips, vfx
except ImportError:
    try:
        from moviepy.editor import ImageClip, AudioFileClip, VideoFileClip, concatenate_videoclips, vfx
    except ImportError:
        ImageClip, AudioFileClip, VideoFileClip, concatenate_videoclips, vfx = None, None, None, None, None

st.set_page_config(page_title="StorySpark AI", page_icon="✨", layout="wide")

st.title("✨ StorySpark AI")
st.caption("Turn simple ideas into complete animated storyboards with AI visuals, voice, captions, and motion video generation.")

class Scene(BaseModel):
    scene_number: int
    character_speaking: str = Field(description="Name of the character speaking")
    dialogue: str = Field(description="The spoken dialogue")
    image_prompt: str = Field(description="Detailed visual prompt highlighting background setting and character actions")
    action_description: str = Field(description="Brief explanation of scene action")

class AnimationStoryboard(BaseModel):
    title: str
    target_audience: str
    main_character_design: str = Field(description="Detailed master description of the main character visual design")
    scenes: list[Scene]

secret_key = st.secrets.get("GEMINI_API_KEY", "")

with st.sidebar:
    st.header("Settings")
    api_key = st.text_input("Gemini API Key", value=secret_key, type="password")
    
    st.subheader("⚙️ Storyboard Controls")
    num_scenes = st.slider("Number of Scenes:", min_value=3, max_value=6, value=5)
    
    aspect_ratio = st.selectbox(
        "📐 Aspect Ratio:",
        ["16:9 Landscape (YouTube)", "9:16 Vertical (TikTok / Reels)"]
    )
    
    st.subheader("🎨 Art & Voice Settings")
    art_style = st.selectbox(
        "Choose Animation Style:",
        ["Vibrant Pixar 3D", "Classic Anime / Studio Ghibli", "Papercraft / Claymation", "Retro Comic Book", "Photorealistic Cinematic"]
    )
    
    voice_accent = st.selectbox(
        "🎙️ Narrator Accent / Language:",
        ["American (en-US)", "British (en-GB)", "Australian (en-AU)", "Indian (en-IN)"]
    )
    
    enable_audio = st.checkbox("Generate Voice & Video Clips 🎙️🎬", value=True)

user_concept = st.text_area(
    "What is your story idea?",
    height=180,
    placeholder="Paste your story idea or full scene-by-scene outline here..."
)

if "9:16" in aspect_ratio:
    VID_WIDTH, VID_HEIGHT = 720, 1280
else:
    VID_WIDTH, VID_HEIGHT = 1280, 720

ACCENT_MAP = {
    "American (en-US)": ("en", "com"),
    "British (en-GB)": ("en", "co.uk"),
    "Australian (en-AU)": ("en", "com.au"),
    "Indian (en-IN)": ("en", "co.in")
}

def clean_text(text):
    if not text:
        return ""
    text = str(text)
    replacements = {'“': '"', '”': '"', '‘': "'", '’': "'", '—': '-', '–': '-', '…': '...'}
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text.encode('ascii', 'ignore').decode('ascii')

def fetch_single_image(args):
    prompt_text, index = args
    clean_prompt = re.sub(r'[^\w\s,-]', '', prompt_text)
    seed = random.randint(1000, 99999)
    
    urls = [
        f"https://image.pollinations.ai/prompt/{urllib.parse.quote(clean_prompt.strip())}?width={VID_WIDTH}&height={VID_HEIGHT}&nologo=true&seed={seed}",
        f"https://picsum.photos/seed/{seed}/{VID_WIDTH}/{VID_HEIGHT}"
    ]
    
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=12) as response:
                img_bytes = response.read()
                if len(img_bytes) > 2000:
                    return img_bytes, f"data:image/jpeg;base64,{base64.b64encode(img_bytes).decode('utf-8')}"
        except Exception:
            continue

    return None, f"https://via.placeholder.com/{VID_WIDTH}x{VID_HEIGHT}.png?text=Image+Unavailable"

def generate_speech(text, accent_key):
    try:
        safe_speech_text = clean_text(text)
        if not safe_speech_text.strip():
            return None
        
        lang_code, tld = ACCENT_MAP.get(accent_key, ("en", "com"))
        tts = gTTS(text=safe_speech_text, lang=lang_code, tld=tld, slow=False)
        fp = BytesIO()
        tts.write_to_fp(fp)
        fp.seek(0)
        return fp
    except Exception:
        return None

def build_motion_video(img_bytes, audio_bytes):
    if not ImageClip or not img_bytes or not audio_bytes:
        return None, None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as img_file:
            img_file.write(img_bytes)
            img_path = img_file.name

        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as audio_file:
            audio_file.write(audio_bytes.getvalue())
            audio_path = audio_file.name

        audio_clip = AudioFileClip(audio_path)
        base_clip = ImageClip(img_path)

        duration = audio_clip.duration if audio_clip.duration > 0 else 4.0

        if hasattr(base_clip, "with_duration"):
            clip = base_clip.with_duration(duration)
        else:
            clip = base_clip.set_duration(duration)

        # Active pixel transformations across time (Ken Burns camera zoom)
        def zoom_transform(get_frame, t):
            frame = get_frame(t)
            # Apply dynamic zoom scaling over time duration
            scale = 1.0 + 0.15 * (t / duration)
            h, w, _ = frame.shape
            nh, nw = int(h / scale), int(w / scale)
            sy, sx = (h - nh) // 2, (w - nw) // 2
            cropped = frame[sy:sy+nh, sx:sx+nw]
            
            try:
                import cv2
                return cv2.resize(cropped, (w, h))
            except ImportError:
                from PIL import Image
                img = Image.fromarray(cropped)
                return __import__("numpy").array(img.resize((w, h), Image.Resampling.LANCZOS))

        if hasattr(clip, "transform"):
            motion_clip = clip.transform(zoom_transform)
        elif hasattr(clip, "fl"):
            motion_clip = clip.fl(lambda gf, t: zoom_transform(gf, t))
        else:
            motion_clip = clip

        if hasattr(motion_clip, "with_audio"):
            video_clip = motion_clip.with_audio(audio_clip)
        else:
            video_clip = motion_clip.set_audio(audio_clip)

        output_path = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4").name
        video_clip.write_videofile(
            output_path, 
            fps=24, 
            codec="libx264", 
            audio_codec="aac", 
            ffmpeg_params=["-pix_fmt", "yuv420p"],
            logger=None
        )

        with open(output_path, "rb") as f:
            video_bytes = f.read()

        for p in [img_path, audio_path]:
            if os.path.exists(p):
                os.remove(p)

        return video_bytes, output_path
    except Exception:
        return None, None

def merge_all_scenes(file_paths):
    try:
        clips = [VideoFileClip(p) for p in file_paths if os.path.exists(p)]
        if not clips:
            return None
        
        final_clip = concatenate_videoclips(clips, method="compose")
        output_full_path = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4").name
        
        final_clip.write_videofile(
            output_full_path,
            fps=24,
            codec="libx264",
            audio_codec="aac",
            ffmpeg_params=["-pix_fmt", "yuv420p"],
            logger=None
        )
        
        with open(output_full_path, "rb") as f:
            full_bytes = f.read()

        if os.path.exists(output_full_path):
            os.remove(output_full_path)
            
        return full_bytes
    except Exception:
        return None

if st.button("Spark Story 🚀", type="primary"):
    if not user_concept:
        st.warning("Please enter a story idea first!")
    else:
        story_status = st.status("Sparking creativity...", expanded=True)
        try:
            active_key = api_key if api_key else secret_key
            client = genai.Client(api_key=active_key) if active_key else genai.Client()

            user_scene_matches = re.findall(r'scene\s*\d+', user_concept, re.IGNORECASE)
            target_count = len(set(user_scene_matches)) if len(set(user_scene_matches)) >= 3 else num_scenes

            fallback_models = ["gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash"]
            response = None

            for model_name in fallback_models:
                try:
                    story_status.write(f"🧠 Drafting {target_count}-scene script ({model_name})...")
                    prompt_query = (
                        f"If the user input contains a multi-scene breakdown, follow that EXACT scene outline, setting, action, and scene count strictly. "
                        f"Otherwise, create EXACTLY {target_count} scenes for: {user_concept}.\n"
                        f"Aesthetic target: {art_style}.\n"
                        f"CRITICAL FOR IMAGES: Describe environment setting and character actions clearly."
                    )
                    response = client.models.generate_content(
                        model=model_name,
                        contents=prompt_query,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=AnimationStoryboard,
                        ),
                    )
                    break
                except Exception:
                    continue

            if not response:
                raise Exception("All Gemini endpoints were busy. Please try again.")

            data = json.loads(response.text)

            story_status.write(f"🎨 Rendering {len(data['scenes'])} motion video scenes...")
            prompts = [f"{s['image_prompt']}, detailed background setting, cinematic lighting, in style of {art_style}" for s in data["scenes"]]
            
            with ThreadPoolExecutor(max_workers=2) as executor:
                raw_image_results = list(executor.map(fetch_single_image, [(p, i) for i, p in enumerate(prompts)]))

            images_bytes_list = [r[0] for r in raw_image_results]
            images_src_list = [r[1] for r in raw_image_results]

            st.success(f"Storyboard: **{data['title']}** (Audience: {data['target_audience']}) | Scenes: {len(data['scenes'])}")

            st.subheader("🎬 Storyboard Scenes with Camera Motion")
            
            scene_temp_files = []
            num_cols = 3 if "16:9" in aspect_ratio else 2
            
            for i in range(0, len(data["scenes"]), num_cols):
                cols = st.columns(num_cols)
                scene_group = data["scenes"][i:i+num_cols]
                
                for idx, scene in enumerate(scene_group):
                    global_idx = i + idx
                    with cols[idx]:
                        st.markdown(f"### Scene {scene['scene_number']}")
                        st.write(f"**Action:** {scene['action_description']}")
                        st.write(f"🗣️ **{scene['character_speaking']}:** \"{scene['dialogue']}\"")
                        
                        audio_fp = None
                        if enable_audio and scene['dialogue']:
                            audio_fp = generate_speech(f"{scene['character_speaking']} says, {scene['dialogue']}", voice_accent)

                        video_bytes, temp_file_path = build_motion_video(
                            images_bytes_list[global_idx], 
                            audio_fp
                        ) if audio_fp and images_bytes_list[global_idx] else (None, None)
                        
                        if temp_file_path:
                            scene_temp_files.append(temp_file_path)

                        if video_bytes:
                            st.video(video_bytes)
                        else:
                            if audio_fp:
                                st.audio(audio_fp, format='audio/mp3')
                            st.image(images_src_list[global_idx], caption=f"Scene {scene['scene_number']} Visual", use_container_width=True)

            if len(scene_temp_files) > 1:
                story_status.write("🎞️ Stitching complete movie file...")
                full_movie_bytes = merge_all_scenes(scene_temp_files)
                if full_movie_bytes:
                    st.divider()
                    st.subheader("📥 Export Complete Movie")
                    st.download_button(
                        label="⬇️ Download Full Story Video (.MP4)",
                        data=full_movie_bytes,
                        file_name=f"{re.sub(r'[^a-zA-Z0-9]', '_', data['title'])}.mp4",
                        mime="video/mp4",
                        type="primary"
                    )

            for p in scene_temp_files:
                if os.path.exists(p):
                    os.remove(p)

            story_status.update(label="Animated Storyboard Complete!", state="complete", expanded=False)

        except Exception as e:
            story_status.update(label="An error occurred.", state="error")
            st.error(f"Error details: {e}")
