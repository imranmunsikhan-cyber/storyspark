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
st.caption("Turn your simple ideas into animated scene storyboards with AI visuals & voice narration.")

class Scene(BaseModel):
    scene_number: int
    character_speaking: str = Field(description="Name of the character speaking")
    dialogue: str = Field(description="The spoken dialogue")
    image_prompt: str = Field(description="Detailed visual prompt for image generation")
    action_description: str = Field(description="Brief explanation of scene action")

class AnimationStoryboard(BaseModel):
    title: str
    target_audience: str
    scenes: list[Scene]

secret_key = st.secrets.get("GEMINI_API_KEY", "")

with st.sidebar:
    st.header("Settings")
    api_key = st.text_input("Gemini API Key", value=secret_key, type="password")
    
    st.subheader("🎨 Art Style Settings")
    art_style = st.selectbox(
        "Choose Animation Style:",
        ["Vibrant Pixar 3D", "Classic Anime / Studio Ghibli", "Papercraft / Claymation", "Retro Comic Book", "Photorealistic Cinematic"]
    )
    enable_audio = st.checkbox("Generate Voice Narration 🎙️", value=True)

user_concept = st.text_area(
    "What is your story idea?",
    placeholder="e.g., A friendly robot learning how to plant sunflowers in an abandoned glass conservatory."
)

def fetch_single_image(prompt_text, index):
    clean_prompt = re.sub(r'[^\w\s,-]', '', prompt_text)
    # Stagger requests to bypass rate-limiting
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
        tts = gTTS(text=text, lang='en', slow=False)
        fp = BytesIO()
        tts.write_to_fp(fp)
        fp.seek(0)
        return fp
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

            fallback_models = ["gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash"]
            response = None
            used_model = ""

            for model_name in fallback_models:
                try:
                    story_status.write(f"🧠 Drafting script ({model_name})...")
                    response = client.models.generate_content(
                        model=model_name,
                        contents=f"Create a 3-scene animation storyboard for: {user_concept}. Aesthetic target: {art_style}.",
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

            story_status.write(f"🎨 Rendering scene images ({art_style})...")
            prompts = [f"{s['image_prompt']}, in style of {art_style}" for s in data["scenes"]]
            
            # Staggered image fetching loop
            image_sources = []
            for idx, p in enumerate(prompts):
                image_sources.append(fetch_single_image(p, idx))

            st.success(f"Storyboard: **{data['title']}** (Audience: {data['target_audience']}) | Model: {used_model}")
            st.subheader("🎬 Storyboard Scenes")
            cols = st.columns(len(data["scenes"]))

            for idx, scene in enumerate(data["scenes"]):
                with cols[idx]:
                    st.markdown(f"### Scene {scene['scene_number']}")
                    st.write(f"**Action:** {scene['action_description']}")
                    st.write(f"🗣️ **{scene['character_speaking']}:** \"{scene['dialogue']}\"")
                    
                    if enable_audio and scene['dialogue']:
                        audio_fp = generate_speech(f"{scene['character_speaking']} says, {scene['dialogue']}")
                        if audio_fp:
                            st.audio(audio_fp, format='audio/mp3')

                    st.image(image_sources[idx], caption=f"Scene {scene['scene_number']} Visual", use_container_width=True)

            story_status.update(label="Storyboard Complete!", state="complete", expanded=False)

        except Exception as e:
            story_status.update(label="An error occurred.", state="error")
            st.error(f"Error details: {e}")
