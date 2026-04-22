from openai import OpenAI
import json
import os
import time

# ===== CONFIG =====
FORGE_API_KEY = os.getenv("FORGE_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")
FORGE_BASE_URL = os.getenv("FORGE_BASE_URL") or os.getenv("OPENAI_BASE_URL") or "https://api.forge.tensorblock.co/v1"
MODEL_NAME = os.getenv("FORGE_MODEL") or "tensorblock/claude-sonnet-4-6"

if not FORGE_API_KEY:
    raise SystemExit("Missing API key. Set FORGE_API_KEY or ANTHROPIC_AUTH_TOKEN.")

OUTPUT_DIR = "log_claude_15"
CSV_FILE = os.path.join(OUTPUT_DIR, "results.csv")
RAW_FILE = os.path.join(OUTPUT_DIR, "raw.txt")

os.makedirs(OUTPUT_DIR, exist_ok=True)

repos = [
"https://github.com/NVIDIA/tao_tutorials",
"https://github.com/NVIDIA-NeMo/Gym",
"https://github.com/mariocandela/ai-avatar",
"https://github.com/snel-repo/Kilosort4",
"https://github.com/nyu-systems/CLM-GS",
"https://github.com/TIO-IKIM/CellViT-plus-plus",
"https://github.com/TIO-IKIM/CellViT-Inference",
"https://github.com/sideprotocol/plonky2-gpu",
"https://github.com/SVRTK/svrtk-docker-gpu",
"https://github.com/PluralisResearch/node0",
"https://github.com/EsmaeilNarimissa/SciDOCX",
"https://github.com/perslev/U-Time",
"https://github.com/nesaorg/bootstrap",
"https://github.com/NVIDIA-AI-Blueprints/pdf-to-podcast"
]

# ===== CLIENT =====
client = OpenAI(
    base_url=FORGE_BASE_URL,
    api_key=FORGE_API_KEY,
)

def clean_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return text.strip()

# ===== INIT CSV =====
with open(CSV_FILE, "w") as f:
    f.write("repo,cpu,ram,disk,gpu,gpu_memory\n")

# Reset raw output each run to avoid mixing old results.
with open(RAW_FILE, "w") as f:
    f.write("")

# ===== LOOP =====
print(f"Using model: {MODEL_NAME}")

for repo in repos:
    print(f"\nProcessing: {repo}")

    prompt = f"""
Given this GitHub repository:
{repo}

Estimate hardware requirements.

You MUST return ONLY valid JSON.

No explanation. No text. No markdown.

Output EXACTLY:

{{
  "cpu": 8,
  "ram": 16,
  "disk": 50,
  "gpu": true,
  "gpu_memory": 8
}}

If unsure, still provide a reasonable estimate.
"""

    try:
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "You extract hardware requirements."},
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )

        response_text = completion.choices[0].message.content

        # save raw
        with open(RAW_FILE, "a") as f:
            f.write(f"{repo}\n{response_text}\n{'='*50}\n")

        cleaned = clean_json(response_text)

        if not cleaned:
            print("⚠ Empty response, skipping")
            continue

        try:
            parsed = json.loads(cleaned)
        except:
            print("⚠ JSON parse failed, skipping")
            continue

        cpu = parsed.get("cpu")
        ram = parsed.get("ram")
        disk = parsed.get("disk")
        gpu = parsed.get("gpu")
        gpu_memory = parsed.get("gpu_memory")

        with open(CSV_FILE, "a") as f:
            f.write(f"{repo},{cpu},{ram},{disk},{gpu},{gpu_memory}\n")

        print("✔ Done")

        time.sleep(1)

    except Exception as e:
        print(f"✗ Failed: {repo}")
        print(e)