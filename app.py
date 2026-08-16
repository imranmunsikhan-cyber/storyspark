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
    from moviepy import ImageClip, AudioFileClip, VideoFileClip
except ImportError:
    try:
        from moviepy.editor import ImageClip, AudioFileClip, VideoFileClip
    except ImportError:
        ImageClip, AudioFileClip, VideoFileClip = None, None, None

st.set_page_config(page_title="StorySpark AI", page_icon="✨", layout="wide")

st.title("✨ StorySpark AI")
st.caption("Turn simple ideas into complete animated storyboards with AI visuals, voice, and dynamic video generation.")

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
    num_scenes = st.slider("Number of Scenes (if not specified in text):", min_value=3, max_value=6, value=5)
    
    st.subheader("🎨 Art Style Settings")
    art_style = st.selectbox(
        "Choose Animation Style:",
        ["Vibrant Pixar 3D", "Classic Anime / Studio Ghibli", "Papercraft / Claymation", "Retro Comic Book", "Photorealistic Cinematic"]
    )
    enable_audio = st.checkbox("Generate Voice & Video Clips 🎙️🎬", value=True)

user_concept = st.text_area(
    "What is your story idea?",
    height=200,
    placeholder="Paste your story idea or full scene-by-scene outline here..."
)

def clean_text(text):
    if not text:
        return ""
    text = str(text)
    replacements = {'“': '"', '”': '"', '‘': "'", '’': "'", '—': '-', '–': '-', '…': '...'}
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text.encode('ascii', 'ignore').decode('ascii')

def fetch_single_video(args):
    prompt_text, index = args
    clean_prompt = re.sub(r'[^\w\s,-]', '', prompt_text)
    seed = random.randint(1000, 99999)
    
    # 100% Free AI motion video endpoint via Pollinations
    video_url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(clean_prompt.strip())}?width=800&height=500&nologo=true&seed={seed}&model=video"
    
    try:
        req = urllib.request.Request(video_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=25) as response:
            vid_bytes = response.read()
            if len(vid_bytes) > 10000:
                return vid_bytes
    except Exception:
        pass
    return None

def generate_speech(text):
    try:
        safe_speech_text = clean_text(text)
        if not safe_speech_text.strip():
            return None
        tts = gTTS(text=safe_speech_text, lang='en', slow=False)
        fp = BytesIO()
        tts.write_to_fp(fp)
        fp.seek(0)
        return fp
    except Exception:
        return None

def combine_video_and_audio(raw_video_bytes, audio_bytes):
    if not raw_video_bytes or not audio_bytes:
        return None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as vid_file:
            vid_file.write(raw_video_bytes)
            vid_path = vid_file.name

        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as audio_file:
            audio_file.write(audio_bytes.getvalue())
            audio_path = audio_file.name

        audio_clip = AudioFileClip(audio_path)
        video_clip = VideoFileClip(vid_path)

        # Loop short motion video to match dialogue length
        if video_clip.duration < audio_clip.duration:
            loops_needed = int(audio_clip.duration / video_clip.duration) + 1
            if hasattr(video_clip, "loop"):
                video_clip = video_clip.loop(n=loops_needed)

        if hasattr(video_clip, "with_duration"):
            video_clip = video_clip.with_duration(audio_clip.duration)
        else:
            video_clip = video_clip.set_duration(audio_clip.duration)

        if hasattr(video_clip, "with_audio"):
            video_clip = video_clip.with_audio(audio_clip)
        else:
            video_clip = video_clip.set_audio(audio_clip)

        output_path = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4").name
        video_clip.write_videofile(output_path, fps=24, codec="libx264", audio_codec="aac", logger=None)

        with open(output_path, "rb") as f:
            result_bytes = f.read()

        for p in [vid_path, audio_path, output_path]:
            if os.path.exists(p):
                os.remove(p)

        return result_bytes
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
                        f"CRITICAL FOR ANIMATION: Describe physical motion, movements, and actions clearly."
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

            story_status.write(f"🎬 Rendering {len(data['scenes'])} moving AI videos...")
            prompts = [f"cinematic moving shot, {s['action_description']}, {s['image_prompt']}, in style of {art_style}" for s in data["scenes"]]
            
            with ThreadPoolExecutor(max_workers=2) as executor:
                raw_video_results = list(executor.map(fetch_single_video, [(p, i) for i, p in enumerate(prompts)]))

            st.success(f"Storyboard: **{data['title']}** (Audience: {data['target_audience']}) | Scenes: {len(data['scenes'])}")

            st.subheader("🎬 Storyboard Scenes with Motion Video")
            
            num_cols = 3
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
                            audio_fp = generate_speech(f"{scene['character_speaking']} says, {scene['dialogue']}")

                        final_video = combine_video_and_audio(raw_video_results[global_idx], audio_fp)
                        
                        if final_video:
                            st.video(final_video)
                        else:
                            if audio_fp:
                                st.audio(audio_fp, format='audio/mp3')

            story_status.update(label="Animated Storyboard Complete!", state="complete", expanded=False)

        except Exception as e:
            story_status.update(label="An error occurred.", state="error")
            st.error(f"Error details: {e}")
