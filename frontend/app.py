import streamlit as st
import httpx
import os
import time

# --- Page Configuration ---
st.set_page_config(
    page_title="Holistika AI Canvas",
    page_icon="🎨",
    layout="wide"
)

# --- API Configuration ---
# This is stored in Streamlit's secrets manager, not in the code.
REPLICATE_API_TOKEN = st.secrets.get("REPLICATE_API_TOKEN")
MODEL_ENDPOINT = st.secrets.get("MODEL_ENDPOINT")

# IMPORTANT: The MODEL_ENDPOINT secret must be set in your Streamlit Cloud app.
# It should look like: "username/model-name:version_id"

# --- UI Elements ---
st.title("🎨 Holistika AI Canvas")
st.markdown("An internal tool to generate visuals using our deployed AI models.")

with st.form("generation_form"):
    prompt = st.text_area(
        "**Enter your creative prompt:**", 
        "A cinematic photo of a bio-luminescent forest at night, detailed, 8k, hyper-realistic",
        height=100
    )

    submitted = st.form_submit_button("Generate Image", use_container_width=True)

# --- Backend Logic ---
if submitted:
    if not REPLICATE_API_TOKEN:
        st.error("CRITICAL: Replicate API token is not configured. Please contact the System Owner.")
    elif not MODEL_ENDPOINT or "..." in MODEL_ENDPOINT:
        st.error("CRITICAL: The MODEL_ENDPOINT secret has not been set in Streamlit Cloud. Please add it in your app's settings.")
    else:
        with st.spinner("Sending prompt to the AI..."):
            headers = {
                "Authorization": f"Token {REPLICATE_API_TOKEN}",
                "Content-Type": "application/json"
            }
            # The input object must match the inputs defined in your predict.py
            payload = {
                "version": MODEL_ENDPOINT.split(':')[1],
                "input": {
                    "prompt": prompt,
                }
            }

            try:
                # 1. Start the prediction
                client = httpx.Client()
                start_response = client.post(
                    "https://api.replicate.com/v1/predictions",
                    headers=headers,
                    json=payload,
                    timeout=60
                )
                start_response.raise_for_status()
                response_json = start_response.json()
                prediction_url = response_json.get("urls", {}).get("get")

                if not prediction_url:
                    st.error("Failed to start prediction. The API did not return a status URL.")
                else:
                    # 2. Poll for the result
                    st.info("AI is generating... This can take up to a minute. Polling for result.")
                    output_image = None
                    status = ""
                    while status not in ["succeeded", "failed", "canceled"]:
                        time.sleep(3) # Wait 3 seconds between polls
                        status_response = client.get(prediction_url, headers=headers)
                        status_response.raise_for_status()
                        status_json = status_response.json()
                        status = status_json.get("status")

                        if status == "succeeded":
                            output_image = status_json.get("output", [])[0]
                            break
                        elif status in ["failed", "canceled"]:
                            st.error(f"Prediction failed or was canceled. Error: {status_json.get('error')}")
                            break

                    if output_image:
                        st.success("Generation complete!")
                        st.image(output_image, caption=prompt, use_column_width=True)

            except httpx.HTTPStatusError as e:
                st.error(f"An API error occurred: {e.response.status_code} - {e.response.text}")
            except Exception as e:
                st.error(f"An unexpected error occurred: {str(e)}")