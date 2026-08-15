import json
import re
import base64
import random
import time
import urllib.parse
import urllib.request
from io import BytesIO
import streamlit as st
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from gtts import gTTS

st.set_page_config(page_title="StorySpark AI", page_icon="✨", layout="wide")

st.title("✨ StorySpark AI")
st.caption("Turn simple ideas into complete animated storyboards with AI visuals, voice, and export features.")

class Scene(BaseModel):
    scene_number: int
    character_speaking: str = Field(description="Name of the character speaking")
    dialogue: str = Field(description="The spoken dialogue")
    image_prompt: str = Field(description="Detailed visual prompt highlighting the background setting, environment elements, and character actions")
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
    enable_audio = st.checkbox("Generate Voice Narration 🎙️", value=True)

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

def fetch_single_image(prompt_text, index):
    clean_prompt = re.sub(r'[^\w\s,-]', '', prompt_text)
    time.sleep(index * 0.4)
    
    seed = random.randint(1000, 999999)
    encoded_prompt = urllib.parse.quote(clean_prompt.strip())
    direct_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=800&height=500&nologo=true&seed={seed}"
    
    req = urllib.request.Request(
        direct_url, 
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    )
    
    for _ in range(2):
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                image_data = response.read()
                if len(image_data) > 2000:
                    return f"data:image/jpeg;base64,{base64.b64encode(image_data).decode('utf-8')}"
        except Exception:
            time.sleep(0.5)
            
    return direct_url

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

def build_html_export(title, audience, character_design, scenes):
    html_content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{clean_text(title)}</title>
<style>
    body {{ font-family: Arial, sans-serif; margin: 30px; line-height: 1.5; color: #222; }}
    h1 {{ color: #111; text-align: center; }}
    .meta {{ text-align: center; color: #555; font-style: italic; margin-bottom: 20px; }}
    .box {{ background: #f4f4f5; padding: 15px; border-radius: 8px; margin-bottom: 25px; border-left: 4px solid #ff4b4b; }}
    .scene {{ margin-bottom: 20px; padding-bottom: 15px; border-bottom: 1px solid #ddd; }}
    .speaker {{ font-weight: bold; color: #0066cc; }}
</style>
</head>
<body>
    <h1>{clean_text(title)}</h1>
    <div class="meta">Target Audience: {clean_text(audience)}</div>
    <div class="box">
        <strong>Master Character Design:</strong><br>
        {clean_text(character_design)}
    </div>
    <h2>Storyboard Scenes</h2>
"""
    for s in scenes:
        html_content += f"""
    <div class="scene">
        ### Scene {s['scene_number']}
        <p><strong>Action:</strong> {clean_text(s['action_description'])}</p>
        <p><span class="speaker">{clean_text(s['character_speaking'])}:</span> "{clean_text(s['dialogue'])}"</p>
    </div>
"""
    html_content += "</body></html>"
    return html_content.encode('utf-8')

if st.button("Spark Story 🚀", type="primary"):
    if not user_concept:
        st.warning("Please enter a story idea first!")
    else:
        story_status = st.status("Sparking creativity...", expanded=True)
        try:
            active_key = api_key if api_key else secret_key
            client = genai.Client(api_key=active_key) if active_key else genai.Client()

            # Check if user explicitly outlined scene count in text
            user_scene_matches = re.findall(r'scene\s*\d+', user_concept, re.IGNORECASE)
            target_count = len(set(user_scene_matches)) if len(set(user_scene_matches)) >= 3 else num_scenes

            fallback_models = ["gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash"]
            response = None
            used_model = ""

            for model_name in fallback_models:
                try:
                    story_status.write(f"🧠 Drafting {target_count}-scene script ({model_name})...")
                    prompt_query = (
                        f"If the user input contains a multi-scene breakdown (e.g., Scene 1, Scene 2...), follow that EXACT scene outline, setting, action, and scene count strictly. "
                        f"Otherwise, create EXACTLY {target_count} scenes for: {user_concept}.\n"
                        f"Aesthetic target: {art_style}.\n"
                        f"CRITICAL FOR IMAGES: In every scene's image_prompt, describe the full environment/setting background clearly (e.g., hospital room, dusty attic, cafeteria) along with character actions, so images show the complete scene instead of just close-up portraits."
                    )
                    response = client.models.generate_content(
                        model=model_name,
                        contents=prompt_query,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=AnimationStoryboard,
                        ),
                    )
                    used_model = model_name
                    break
                except Exception:
                    continue

            if not response:
                raise Exception("All Gemini endpoints were busy. Please try again.")

            data = json.loads(response.text)

            story_status.write(f"🎨 Rendering {len(data['scenes'])} visual scenes ({art_style})...")
            prompts = [f"{s['image_prompt']}, detailed environment background, widescreen cinematic composition, in style of {art_style}" for s in data["scenes"]]
            
            image_sources = []
            for idx, p in enumerate(prompts):
                image_sources.append(fetch_single_image(p, idx))

            st.success(f"Storyboard: **{data['title']}** (Audience: {data['target_audience']}) | Scenes: {len(data['scenes'])}")
            
            with st.expander("👤 Master Character Visual Design"):
                st.write(data["main_character_design"])

            st.subheader("🎬 Storyboard Scenes")
            
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
                        
                        if enable_audio and scene['dialogue']:
                            audio_fp = generate_speech(f"{scene['character_speaking']} says, {scene['dialogue']}")
                            if audio_fp:
                                st.audio(audio_fp, format='audio/mp3')

                        st.image(image_sources[global_idx], caption=f"Scene {scene['scene_number']} Visual", use_container_width=True)

            html_data = build_html_export(data["title"], data["target_audience"], data["main_character_design"], data["scenes"])
            st.download_button(
                label="📄 Export Storyboard (HTML/Print)",
                data=html_data,
                file_name=f"{clean_text(data['title']).lower().replace(' ', '_')}_storyboard.html",
                mime="text/html"
            )

            story_status.update(label="Storyboard Complete!", state="complete", expanded=False)

        except Exception as e:
            story_status.update(label="An error occurred.", state="error")
            st.error(f"Error details: {e}")
