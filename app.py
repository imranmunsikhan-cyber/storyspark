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
    from moviepy import ImageClip, AudioFileClip
except ImportError:
    try:
        from moviepy.editor import ImageClip, AudioFileClip
    except ImportError:
        ImageClip, AudioFileClip = None, None

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
    hf_token = st.text_input("HuggingFace Free API Token (for AI Motion Video)", type="password")
    
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

def fetch_single_image(args):
    prompt_text, index = args
    clean_prompt = re.sub(r'[^\w\s,-]', '', prompt_text)
    
    providers = [
        f"https://image.pollinations.ai/prompt/{urllib.parse.quote(clean_prompt.strip())}?width=800&height=500&nologo=true&seed={random.randint(1000, 99999)}",
        f"https://picsum.photos/seed/{random.randint(1000, 99999)}/800/500"
    ]
    
    for url in providers:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                img_bytes = response.read()
                if len(img_bytes) > 2000:
                    return img_bytes, f"data:image/jpeg;base64,{base64.b64encode(img_bytes).decode('utf-8')}"
        except Exception:
            continue

    return None, "https://via.placeholder.com/800x500.png?text=Image+Unavailable"

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

def generate_hf_video(img_bytes, prompt, hf_token):
    if not hf_token or not img_bytes:
        return None
    try:
        # Use Hugging Face Wan2.1 / LTX-Video Inference API
        api_url = "https://api-inference.huggingface.co/models/Wan-AI/Wan2.1-I2V-14B-480P"
        headers = {"Authorization": f"Bearer {hf_token}"}
        
        base64_img = base64.b64encode(img_bytes).decode('utf-8')
        payload = {
            "inputs": {
                "image": f"data:image/jpeg;base64,{base64_img}",
                "prompt": prompt
            }
        }
        
        req = urllib.request.Request(api_url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.read()
    except Exception:
        return None

def create_scene_video(img_bytes, audio_bytes, prompt, hf_token):
    if not img_bytes or not audio_bytes:
        return None
    try:
        # Try Hugging Face dynamic AI Video first if HF Token is provided
        ai_video_bytes = generate_hf_video(img_bytes, prompt, hf_token) if hf_token else None
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as img_file:
            img_file.write(img_bytes)
            img_path = img_file.name

        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as audio_file:
            audio_file.write(audio_bytes.getvalue())
            audio_path = audio_file.name

        audio_clip = AudioFileClip(audio_path)
        
        if ai_video_bytes:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as vid_file:
                vid_file.write(ai_video_bytes)
                video_clip_path = vid_file.name
            video_clip = VideoFileClip(video_clip_path)
        else:
            video_clip = ImageClip(img_path)

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
            video_bytes = f.read()

        for p in [img_path, audio_path, output_path]:
            if os.path.exists(p):
                os.remove(p)

        return video_bytes
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
                        f"CRITICAL FOR IMAGES: Describe full environment setting and character actions clearly."
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

            story_status.write(f"🎨 Rendering {len(data['scenes'])} visual scenes...")
            prompts = [f"{s['image_prompt']}, detailed background, widescreen composition, in style of {art_style}" for s in data["scenes"]]
            
            with ThreadPoolExecutor(max_workers=2) as executor:
                raw_image_results = list(executor.map(fetch_single_image, [(p, i) for i, p in enumerate(prompts)]))

            images_bytes_list = [r[0] for r in raw_image_results]
            images_src_list = [r[1] for r in raw_image_results]

            st.success(f"Storyboard: **{data['title']}** (Audience: {data['target_audience']}) | Scenes: {len(data['scenes'])}")

            st.subheader("🎬 Storyboard Scenes & Dynamic Video Clips")
            
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

                        video_data = create_scene_video(
                            images_bytes_list[global_idx], 
                            audio_fp, 
                            scene['action_description'], 
                            hf_token
                        ) if audio_fp and images_bytes_list[global_idx] else None
                        
                        if video_data:
                            st.video(video_data)
                        else:
                            if audio_fp:
                                st.audio(audio_fp, format='audio/mp3')
                            st.image(images_src_list[global_idx], caption=f"Scene {scene['scene_number']} Visual", use_container_width=True)

            story_status.update(label="Storyboard Complete!", state="complete", expanded=False)

        except Exception as e:
            story_status.update(label="An error occurred.", state="error")
            st.error(f"Error details: {e}")
