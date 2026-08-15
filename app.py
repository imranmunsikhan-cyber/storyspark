import json
import re
import base64
import urllib.parse
import urllib.request
import concurrent.futures
import streamlit as st
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

st.set_page_config(page_title="StorySpark AI", page_icon="✨", layout="wide")

st.title("✨ StorySpark AI")
st.caption("Turn your simple ideas into animated scene storyboards with custom visual styles.")

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

with st.sidebar:
    st.header("Settings")
    api_key = st.text_input("Gemini API Key", type="password")
    
    st.subheader("🎨 Art Style Settings")
    art_style = st.selectbox(
        "Choose Animation Style:",
        ["Vibrant Pixar 3D", "Classic Anime / Studio Ghibli", "Papercraft / Claymation", "Retro Comic Book", "Photorealistic Cinematic"]
    )
    st.info("💡 API models and image generation remain 100% free.")

user_concept = st.text_area(
    "What is your story idea?",
    placeholder="e.g., A young red fox sitting in a snowy forest clearing at dawn."
)

def fetch_single_image(prompt_text):
    clean_prompt = re.sub(r'[^\w\s,-]', '', prompt_text)
    encoded_prompt = urllib.parse.quote(clean_prompt.strip())
    url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=800&height=500&nologo=true"
    
    req = urllib.request.Request(
        url, 
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    )
    
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            image_data = response.read()
            return f"data:image/jpeg;base64,{base64.b64encode(image_data).decode('utf-8')}"
    except Exception:
        return url

if st.button("Spark Story 🚀", type="primary"):
    if not user_concept:
        st.warning("Please enter a story idea first!")
    else:
        story_status = st.status("Thinking...", expanded=True)
        try:
            if api_key:
                client = genai.Client(api_key=api_key)
            else:
                client = genai.Client()

            fallback_models = ["gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash"]
            response = None
            used_model = ""

            for model_name in fallback_models:
                try:
                    story_status.write(f"🧠 Consulting Gemini ({model_name})...")
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
                except Exception as model_err:
                    story_status.write(f"⚠️ {model_name} busy, retrying fallback...")
                    continue

            if not response:
                raise Exception("Gemini endpoints busy. Please retry.")

            data = json.loads(response.text)

            story_status.write(f"🎨 Rendering images in parallel ({art_style})...")
            
            prompts = [f"{s['image_prompt']}, in style of {art_style}" for s in data["scenes"]]
            with concurrent.futures.ThreadPoolExecutor() as executor:
                image_sources = list(executor.map(fetch_single_image, prompts))

            st.success(f"Storyboard: **{data['title']}** (Audience: {data['target_audience']}) | Style: {art_style}")
            st.subheader("🎬 Storyboard Scenes")
            cols = st.columns(len(data["scenes"]))

            for idx, scene in enumerate(data["scenes"]):
                with cols[idx]:
                    st.markdown(f"### Scene {scene['scene_number']}")
                    st.write(f"**Action:** {scene['action_description']}")
                    st.write(f"🗣️ **{scene['character_speaking']}:** \"{scene['dialogue']}\"")
                    
                    st.image(image_sources[idx], caption=f"Scene {scene['scene_number']} Visual", use_container_width=True)
                    
                    with st.expander("Show Raw Image Prompt"):
                        st.caption(f"🎨: {scene['image_prompt']}")

            story_status.update(label="Storyboard Complete!", state="complete", expanded=False)

        except Exception as e:
            story_status.update(label="An error occurred.", state="error")
            st.error(f"Error details: {e}")
