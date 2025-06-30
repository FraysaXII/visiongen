import json
import os
import httpx
import time
import subprocess
from cog import BasePredictor, Input, Path
from urllib.parse import urlparse
import websocket
import shutil

COMFYUI_OUTPUT_DIR = "output"
COMFYUI_INPUT_DIR = "input"

# Helper function to download files efficiently
def download_file(url, dest_folder):
    if not os.path.exists(dest_folder):
        os.makedirs(dest_folder)

    filename = os.path.basename(urlparse(url))
    dest_path = os.path.join(dest_folder, filename)

    if not os.path.exists(dest_path):
        print(f"Downloading {url} to {dest_path}...")
        with httpx.stream("GET", url, follow_redirects=True, timeout=60) as r:
            with open(dest_path, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
    return filename

class Predictor(BasePredictor):
    def setup(self):
        """This method is called once when the container boots."""
        print("Starting setup...")

        # Clean up previous run directories if they exist
        if os.path.exists(COMFYUI_OUTPUT_DIR):
            shutil.rmtree(COMFYUI_OUTPUT_DIR)
        if os.path.exists(COMFYUI_INPUT_DIR):
            shutil.rmtree(COMFYUI_INPUT_DIR)
        os.makedirs(COMFYUI_OUTPUT_DIR)
        os.makedirs(COMFYUI_INPUT_DIR)

        # Start the ComfyUI server in the background
        self.comfy_proc = subprocess.Popen(["python", "main.py", "--listen", "127.0.0.1", "--output-directory", COMFYUI_OUTPUT_DIR])

        # --- Download Models ---
        # This is where you download your required models.
        download_file(
            "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors",
            "models/checkpoints"
        )

        # Load the workflow "recipe" from the JSON file
        with open('workflow_api.json', 'r') as f:
            self.workflow_api = json.load(f)

        # Wait until the ComfyUI server is ready
        self._wait_for_server("http://127.0.0.1:8188/history")
        print("Setup complete.")

    def _wait_for_server(self, url, timeout=60):
        start = time.time()
        while time.time() - start < timeout:
            try:
                httpx.get(url)
                print("Server is ready.")
                return
            except httpx.ConnectError:
                time.sleep(0.5)
        raise RuntimeError("Server did not start in time.")

    def predict(
        self,
        prompt: str = Input(description="The text prompt for image generation."),
        # You can add more inputs here, e.g., negative_prompt, seed, etc.
    ) -> Path:
        """This method is called for each prediction request."""
        print(f"Received prediction request with prompt: {prompt}")

        # --- Inject the user's prompt into the workflow recipe ---
        # IMPORTANT: The node ID "6" corresponds to the positive prompt node
        # in our example workflow_api.json. You MUST find the correct ID
        # for the prompt node in YOUR OWN workflow file.
        prompt_node_id = "6"
        self.workflow_api[prompt_node_id]["inputs"]["text"] = prompt

        # --- Send the workflow to the ComfyUI API ---
        ws = websocket.WebSocket()
        ws.connect("ws://127.0.0.1:8188/ws?clientId=replicate")

        req = {"prompt": self.workflow_api}
        res_json = httpx.post("http://127.0.0.1:8188/prompt", json=req).json()
        prompt_id = res_json['prompt_id']

        # --- Wait for the result ---
        while True:
            out = ws.recv()
            if isinstance(out, str):
                message = json.loads(out)
                if message['type'] == 'executed':
                    data = message['data']
                    # Check if the final node has executed
                    if data['node'] == list(self.workflow_api.keys())[-1]:
                        images = data['output']['images']
                        image_data = images[0]

                        # The output is in the ComfyUI output directory
                        output_path = os.path.join(COMFYUI_OUTPUT_DIR, image_data['filename'])
                        print(f"Image generated at path: {output_path}")
                        ws.close()
                        return Path(output_path)