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
from PIL import Image, ImageDraw

try:
    from moviepy import (
        ImageClip, AudioFileClip, VideoFileClip, TextClip, 
        CompositeVideoClip, CompositeAudioClip, concatenate_videoclips, afx
    )
except ImportError:
    try:
        from moviepy.editor import (
            ImageClip, AudioFileClip, VideoFileClip, TextClip, 
            CompositeVideoClip, CompositeAudioClip, concatenate_videoclips, afx
        )
    except ImportError:
        ImageClip, AudioFileClip, VideoFileClip, TextClip, CompositeVideoClip, CompositeAudioClip, concatenate_videoclips, afx = [None] * 8

st.set_page_config(page_title="StorySpark AI", page_icon="✨", layout="wide")

st.title("✨ StorySpark AI Engine")
st.caption("ToonBees-Style Animation Studio: Enforced Video Generation & Dynamic Fallbacks.")

class Scene(BaseModel):
    scene_number: int
    character_speaking: str = Field(description="Name of the character speaking or Narrator")
    dialogue: str = Field(description="Spoken dialogue or narrative commentary.")
    image_prompt: str = Field(description="Detailed visual prompt depicting background setting and action.")
    action_description: str = Field(description="Brief explanation of scene action")

class AnimationStoryboard(BaseModel):
    title: str
    target_audience: str
    main_character_name: str = Field(description="Name of primary character")
    main_character_design: str = Field(description="Detailed physical traits of the main character")
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
    
    st.subheader("🎨 Art & Audio Settings")
    art_style = st.selectbox(
        "Choose Animation Style:",
        ["Vibrant Pixar 3D", "Classic Anime / Studio Ghibli", "Papercraft / Claymation", "Retro Comic Book", "Photorealistic Cinematic"]
    )
    
    voice_accent = st.selectbox(
        "🎙️ Narrator Accent / Language:",
        ["American (en-US)", "British (en-GB)", "Australian (en-AU)", "Indian (en-IN)"]
    )
    
    enable_audio = st.checkbox("Generate Voice & Motion Clips 🎙️🎬", value=True)
    enable_subtitles = st.checkbox("Burn-In Dynamic Subtitles 💬", value=True)
    enable_bgm = st.checkbox("Add Background Music Track 🎵", value=True)

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

BGM_URL = "https://cdn.pixabay.com/download/audio/2022/05/27/audio_1808fbf07a.mp3"

def clean_text(text):
    if not text:
        return ""
    text = str(text)
    replacements = {'“': '"', '”': '"', '‘': "'", '’': "'", '—': '-', '–': '-', '…': '...'}
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text.encode('ascii', 'ignore').decode('ascii')

def create_fallback_image_bytes(text_label="Scene Visual"):
    img = Image.new('RGB', (VID_WIDTH, VID_HEIGHT), color=(30, 35, 45))
    draw = ImageDraw.Draw(img)
    draw.text((VID_WIDTH // 3, VID_HEIGHT // 2), f"Rendering Scene: {text_label[:30]}", fill=(255, 255, 255))
    buf = BytesIO()
    img.save(buf, format='JPEG')
    return buf.getvalue()

def fetch_single_image(args):
    prompt_text, index = args
    clean_p = re.sub(r'[^a-zA-Z0-9\s,-]', '', prompt_text)
    clean_p = ' '.join(clean_p.split())[:180]
    
    for attempt in range(3):
        seed = random.randint(1000, 99999)
        url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(clean_p)}?width={VID_WIDTH}&height={VID_HEIGHT}&nologo=true&seed={seed}"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            with urllib.request.urlopen(req, timeout=15) as response:
                img_bytes = response.read()
                if len(img_bytes) > 2000:
                    return img_bytes, f"data:image/jpeg;base64,{base64.b64encode(img_bytes).decode('utf-8')}"
        except Exception:
            time.sleep(1)

    fallback_b = create_fallback_image_bytes(prompt_text)
    return fallback_b, f"data:image/jpeg;base64,{base64.b64encode(fallback_b).decode('utf-8')}"

def generate_speech_file(text, accent_key):
    try:
        safe_speech_text = clean_text(text)
        if not safe_speech_text.strip():
            safe_speech_text = "Observing the scene carefully."
        
        lang_code, tld = ACCENT_MAP.get(accent_key, ("en", "com"))
        tts = gTTS(text=safe_speech_text, lang=lang_code, tld=tld, slow=False)
        
        temp_audio = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        tts.save(temp_audio.name)
        return temp_audio.name
    except Exception:
        return None

def fetch_bgm_file():
    try:
        req = urllib.request.Request(BGM_URL, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            bgm_bytes = response.read()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
                f.write(bgm_bytes)
                return f.name
    except Exception:
        return None

def build_motion_video(img_bytes, audio_path, subtitle_text="", scene_idx=0):
    if not ImageClip or not img_bytes:
        return None, None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as img_file:
            img_file.write(img_bytes)
            img_path = img_file.name

        duration = 4.0
        audio_clip = None

        if audio_path and os.path.exists(audio_path):
            try:
                audio_clip = AudioFileClip(audio_path)
                duration = audio_clip.duration if audio_clip.duration > 0 else 4.0
            except Exception:
                audio_clip = None

        base_clip = ImageClip(img_path)

        if hasattr(base_clip, "with_duration"):
            clip = base_clip.with_duration(duration)
        else:
            clip = base_clip.set_duration(duration)

        motion_mode = scene_idx % 3

        def pan_and_scan_transform(get_frame, t):
            frame = get_frame(t)
            h, w, _ = frame.shape
            progress = t / duration

            if motion_mode == 0:
                scale = 1.05 + (0.10 * progress)
                off_x = int((w * 0.03) * progress)
                off_y = 0
            elif motion_mode == 1:
                scale = 1.15 - (0.08 * progress)
                off_x = 0
                off_y = int((h * 0.03) * progress)
            else:
                scale = 1.0 + (0.12 * progress)
                off_x = 0
                off_y = 0

            nh, nw = int(h / scale), int(w / scale)
            sy = max(0, min(h - nh, ((h - nh) // 2) + off_y))
            sx = max(0, min(w - nw, ((w - nw) // 2) + off_x))
            cropped = frame[sy:sy+nh, sx:sx+nw]

            try:
                import cv2
                return cv2.resize(cropped, (w, h))
            except ImportError:
                img = Image.fromarray(cropped)
                return __import__("numpy").array(img.resize((w, h), Image.Resampling.LANCZOS))

        if hasattr(clip, "transform"):
            motion_clip = clip.transform(pan_and_scan_transform)
        elif hasattr(clip, "fl"):
            motion_clip = clip.fl(lambda gf, t: pan_and_scan_transform(gf, t))
        else:
            motion_clip = clip

        if enable_subtitles and subtitle_text.strip() and TextClip and CompositeVideoClip:
            try:
                txt_clip = TextClip(
                    subtitle_text,
                    fontsize=28 if "16:9" in aspect_ratio else 34,
                    color='white',
                    bg_color='black',
                    size=(int(VID_WIDTH * 0.85), None),
                    method='caption'
                )
                if hasattr(txt_clip, "with_duration"):
                    txt_clip = txt_clip.with_duration(duration).with_position(('center', int(VID_HEIGHT * 0.82)))
                else:
                    txt_clip = txt_clip.set_duration(duration).set_position(('center', int(VID_HEIGHT * 0.82)))
                
                motion_clip = CompositeVideoClip([motion_clip, txt_clip])
            except Exception:
                pass

        if audio_clip:
            if hasattr(motion_clip, "with_audio"):
                video_clip = motion_clip.with_audio(audio_clip)
            else:
                video_clip = motion_clip.set_audio(audio_clip)
        else:
            video_clip = motion_clip

        output_path = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4").name
        video_clip.write_videofile(
            output_path, 
            fps=24, 
            codec="libx264", 
            audio_codec="aac" if audio_clip else None, 
            ffmpeg_params=["-pix_fmt", "yuv420p"],
            logger=None
        )

        with open(output_path, "rb") as f:
            video_bytes = f.read()

        for p in [img_path, audio_path]:
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

        return video_bytes, output_path
    except Exception:
        return None, None

def merge_all_scenes(file_paths, include_bgm=False):
    try:
        clips = [VideoFileClip(p) for p in file_paths if os.path.exists(p)]
        if not clips:
            return None
        
        final_clip = concatenate_videoclips(clips, method="compose")
        bgm_path = fetch_bgm_file() if include_bgm else None

        if bgm_path and os.path.exists(bgm_path) and CompositeAudioClip:
            try:
                bgm_audio = AudioFileClip(bgm_path)
                bgm_audio = bgm_audio.subclip(0, min(bgm_audio.duration, final_clip.duration))
                
                if hasattr(bgm_audio, "volumex"):
                    bgm_audio = bgm_audio.volumex(0.15)
                elif hasattr(afx, "volumex"):
                    bgm_audio = afx.volumex(bgm_audio, 0.15)

                if final_clip.audio:
                    combined_audio = CompositeAudioClip([final_clip.audio, bgm_audio])
                else:
                    combined_audio = bgm_audio

                if hasattr(final_clip, "with_audio"):
                    final_clip = final_clip.with_audio(combined_audio)
                else:
                    final_clip = final_clip.set_audio(combined_audio)
            except Exception:
                pass

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
        if bgm_path and os.path.exists(bgm_path):
            os.remove(bgm_path)
            
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
                    story_status.write(f"🧠 Drafting script & visual concept ({model_name})...")
                    prompt_query = (
                        f"If the user input contains a multi-scene breakdown, follow that EXACT scene outline, setting, action, and scene count strictly. "
                        f"Otherwise, create EXACTLY {target_count} scenes for: {user_concept}.\n"
                        f"Aesthetic target: {art_style}.\n"
                        f"CRITICAL: Always generate dialogue or spoken narration text for EVERY scene."
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
            char_design = data.get("main_character_design", "")
            char_name = data.get("main_character_name", "Character")

            story_status.write(f"🎨 Generating {len(data['scenes'])} scenes and compiling motion video...")

            prompts = []
            for s in data["scenes"]:
                scene_p = f"{art_style} style, {s['image_prompt']}, {char_name} {char_design}, high detailed animation"
                prompts.append(scene_p)
            
            # Fetch sequentially to avoid rate-limiting image APIs
            raw_image_results = [fetch_single_image((p, i)) for i, p in enumerate(prompts)]

            images_bytes_list = [r[0] for r in raw_image_results]
            images_src_list = [r[1] for r in raw_image_results]

            st.success(f"Storyboard: **{data['title']}** | Style: *{art_style}*")

            st.subheader("🎬 Storyboard Scenes with Motion & Audio")
            
            scene_temp_files = []
            num_cols = 3 if "16:9" in aspect_ratio else 2
            
            for i in range(0, len(data["scenes"]), num_cols):
                cols = st.columns(num_cols)
                scene_group = data["scenes"][i:i+num_cols]
                
                for idx, scene in enumerate(scene_group):
                    global_idx = i + idx
                    with cols[idx]:
                        speaker = scene['character_speaking'] if scene['character_speaking'] else "Narrator"
                        speech_text = scene['dialogue'] if scene['dialogue'].strip() else scene['action_description']
                        
                        st.markdown(f"### Scene {scene['scene_number']}")
                        st.write(f"**Action:** {scene['action_description']}")
                        st.write(f"🗣️ **{speaker}:** \"{speech_text}\"")
                        
                        audio_path = None
                        if enable_audio:
                            audio_path = generate_speech_file(speech_text, voice_accent)

                        video_bytes, temp_file_path = build_motion_video(
                            images_bytes_list[global_idx], 
                            audio_path,
                            subtitle_text=speech_text,
                            scene_idx=global_idx
                        )
                        
                        if temp_file_path:
                            scene_temp_files.append(temp_file_path)

                        if video_bytes:
                            st.video(video_bytes)
                        else:
                            if audio_path and os.path.exists(audio_path):
                                st.audio(audio_path, format='audio/mp3')
                            st.image(images_src_list[global_idx], caption=f"Scene {scene['scene_number']} Visual", use_container_width=True)

            if len(scene_temp_files) > 1:
                story_status.write("🎞️ Stitching complete movie with background music...")
                full_movie_bytes = merge_all_scenes(scene_temp_files, include_bgm=enable_bgm)
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
                    try:
                        os.remove(p)
                    except Exception:
                        pass

            story_status.update(label="Animated Storyboard Complete!", state="complete", expanded=False)

        except Exception as e:
            story_status.update(label="An error occurred.", state="error")
            st.error(f"Error details: {e}")
