from openai import OpenAI
import json
import os
import time

# ===== CONFIG =====
FORGE_API_KEY = os.getenv("FORGE_API_KEY")

OUTPUT_DIR = "log_codex"
CSV_FILE = os.path.join(OUTPUT_DIR, "results_hardware.csv")
RAW_FILE = os.path.join(OUTPUT_DIR, "raw_hardware.txt")

os.makedirs(OUTPUT_DIR, exist_ok=True)

repos = [
("tao_tutorials", "https://github.com/NVIDIA/tao_tutorials"),
("NeMo-Gym", "https://github.com/NVIDIA-NeMo/Gym"),
("ai-avatar", "https://github.com/mariocandela/ai-avatar"),
("Kilosort4", "https://github.com/snel-repo/Kilosort4"),
("CLM-GS", "https://github.com/nyu-systems/CLM-GS"),
("CellViT-plus-plus", "https://github.com/TIO-IKIM/CellViT-plus-plus"),
("CellViT-Inference", "https://github.com/TIO-IKIM/CellViT-Inference"),
("plonky2-gpu", "https://github.com/sideprotocol/plonky2-gpu"),
("svrtk-docker-gpu", "https://github.com/SVRTK/svrtk-docker-gpu"),
("node0", "https://github.com/PluralisResearch/node0"),
("SciDOCX", "https://github.com/EsmaeilNarimissa/SciDOCX"),
("U-Time", "https://github.com/perslev/U-Time"),
("bootstrap", "https://github.com/nesaorg/bootstrap"),
("pdf-to-podcast", "https://github.com/NVIDIA-AI-Blueprints/pdf-to-podcast")
]

# ===== CLIENT =====
client = OpenAI(
    base_url="https://api.forge.tensorblock.co/v1",
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

# ===== LOOP =====
for name, repo in repos:
    print(f"\nProcessing: {name}")

    prompt = f"""
Given this GitHub repository:
{repo}

Extract or infer the hardware requirements.

Return ONLY JSON in EXACT format:
{{
  "cpu": integer (cores, or estimate),
  "ram": integer (GB),
  "disk": integer (GB),
  "gpu": true/false,
  "gpu_memory": integer (GB, 0 if none)
}}

If values are missing, estimate conservatively.
Do NOT include text explanation.
"""

    try:
        completion = client.chat.completions.create(
            model="OpenAI/gpt-4o",
            messages=[
                {"role": "system", "content": "You extract hardware requirements from repositories."},
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )

        response_text = completion.choices[0].message.content

        # save raw
        with open(RAW_FILE, "a") as f:
            f.write(f"{name}\n{response_text}\n{'='*50}\n")

        # parse
        cleaned = clean_json(response_text)
        parsed = json.loads(cleaned)

        cpu = parsed.get("cpu")
        ram = parsed.get("ram")
        disk = parsed.get("disk")
        gpu = parsed.get("gpu")
        gpu_memory = parsed.get("gpu_memory")

        with open(CSV_FILE, "a") as f:
            f.write(f"{name},{cpu},{ram},{disk},{gpu},{gpu_memory}\n")

        print("✔ Done")

        time.sleep(1)

    except Exception as e:
        print(f"✗ Failed: {name}")
        print(e)