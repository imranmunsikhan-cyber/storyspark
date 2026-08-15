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
from fpdf import FPDF

st.set_page_config(page_title="StorySpark AI", page_icon="✨", layout="wide")

st.title("✨ StorySpark AI")
st.caption("Turn simple ideas into complete animated storyboards with AI visuals, voice, and export features.")

class Scene(BaseModel):
    scene_number: int
    character_speaking: str = Field(description="Name of the character speaking")
    dialogue: str = Field(description="The spoken dialogue")
    image_prompt: str = Field(description="Detailed visual prompt including consistent character design")
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
    num_scenes = st.slider("Number of Scenes:", min_value=3, max_value=6, value=3)
    
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

def sanitize_text(txt):
    return str(txt).encode('ascii', 'replace').decode('ascii')

def create_pdf(title, audience, character_design, scenes):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    
    pdf.set_font("Helvetica", "B", 16)
    pdf.multi_cell(0, 8, sanitize_text(title), align="C")
    
    pdf.set_font("Helvetica", "I", 10)
    pdf.multi_cell(0, 6, f"Target Audience: {sanitize_text(audience)}", align="C")
    pdf.ln(4)
    
    pdf.set_font("Helvetica", "B", 11)
    pdf.multi_cell(0, 6, "Master Character Design:")
    pdf.set_font("Helvetica", "", 9)
    pdf.multi_cell(0, 5, sanitize_text(character_design))
    pdf.ln(6)
    
    for scene in scenes:
        pdf.set_font("Helvetica", "B", 11)
        pdf.multi_cell(0, 6, f"Scene {scene['scene_number']}")
        
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 5, f"Action: {sanitize_text(scene['action_description'])}")
        pdf.multi_cell(0, 5, f"Speaker ({sanitize_text(scene['character_speaking'])}): \"{sanitize_text(scene['dialogue'])}\"")
        pdf.ln(4)
        
    pdf_output = BytesIO()
    pdf.output(pdf_output)
    pdf_output.seek(0)
    return pdf_output

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
                    story_status.write(f"🧠 Drafting {num_scenes}-scene script ({model_name})...")
                    prompt_query = (
                        f"Create EXACTLY {num_scenes} scenes in the storyboard for: {user_concept}. "
                        f"Aesthetic target: {art_style}. Include static key features from main_character_design in each scene's image_prompt."
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
            prompts = [f"{s['image_prompt']}, in style of {art_style}" for s in data["scenes"]]
            
            image_sources = []
            for idx, p in enumerate(prompts):
                image_sources.append(fetch_single_image(p, idx))

            st.success(f"Storyboard: **{data['title']}** (Audience: {data['target_audience']}) | Scenes: {len(data['scenes'])}")
            
            with st.expander("👤 Master Character Visual Design"):
                st.write(data["main_character_design"])

            st.subheader("🎬 Storyboard Scenes")
            
            # Responsive layout grid (3 columns per row)
            num_cols = 3 if len(data["scenes"]) >= 3 else len(data["scenes"])
            
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

            pdf_file = create_pdf(data["title"], data["target_audience"], data["main_character_design"], data["scenes"])
            st.download_button(
                label="📄 Download Storyboard PDF",
                data=pdf_file,
                file_name=f"{data['title'].lower().replace(' ', '_')}_storyboard.pdf",
                mime="application/pdf"
            )

            story_status.update(label="Storyboard Complete!", state="complete", expanded=False)

        except Exception as e:
            story_status.update(label="An error occurred.", state="error")
            st.error(f"Error details: {e}")
