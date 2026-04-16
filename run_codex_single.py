from openai import OpenAI
import json
import os

# ===== CONFIG =====
FORGE_API_KEY = os.getenv("FORGE_API_KEY")  
OUTPUT_FILE = "log_codex.txt"

REPO_URL = "https://github.com/yrcong/RelTR"

# ===== CLIENT =====
client = OpenAI(
    base_url="https://api.forge.tensorblock.co/v1",
    api_key=FORGE_API_KEY,
)

# ===== PROMPT =====
prompt = f"""
You are an expert in systems and machine learning infrastructure.

Given this GitHub repository:
{REPO_URL}

Estimate the required hardware to SET UP and RUN the project.

Return ONLY a JSON object with:
{{
  "cpu": number of cores,
  "ram": GB,
  "disk": GB,
  "gpu": true/false,
  "gpu_memory": GB (0 if no GPU)
}}

Be realistic and slightly conservative.
"""

# ===== API CALL =====
completion = client.chat.completions.create(
    model="OpenAI/gpt-4o",  # change if needed after model.list()
    messages=[
        {"role": "system", "content": "You estimate hardware requirements."},
        {"role": "user", "content": prompt}
    ],
    temperature=0
)

response_text = completion.choices[0].message.content

# ===== SAVE OUTPUT =====
with open(OUTPUT_FILE, "a") as f:
    f.write(f"Repo: {REPO_URL}\n")
    f.write(response_text + "\n")
    f.write("=" * 50 + "\n")

# ===== PRINT =====
print("Response:")
print(response_text)

# ===== OPTIONAL: try parsing JSON =====
def clean_json(text):
    text = text.strip()
    
    if text.startswith("```"):
        text = text.split("```")[1]   # remove first ```
        if text.startswith("json"):
            text = text[4:]          # remove 'json'
    
    return text.strip()

cleaned = clean_json(response_text)

try:
    parsed = json.loads(cleaned)
    print("\nParsed JSON:")
    print(parsed)
except:
    print("\nStill failed to parse JSON")