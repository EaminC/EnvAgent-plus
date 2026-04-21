from openai import OpenAI
import json
import os
import time

# ===== CONFIG =====
FORGE_API_KEY = os.getenv("FORGE_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")
FORGE_BASE_URL = os.getenv("FORGE_BASE_URL") or os.getenv("OPENAI_BASE_URL") or "https://api.forge.tensorblock.co/v1"
MODEL_NAME = (
    os.getenv("FORGE_MODEL")
    or os.getenv("ANTHROPIC_MODEL")
    or "Fireworks/accounts/fireworks/models/qwen3-coder-480b-a35b-instruct"
)

if not FORGE_API_KEY:
    raise SystemExit(
        "Missing API key. Set FORGE_API_KEY or ANTHROPIC_AUTH_TOKEN in your environment before running."
    )

OUTPUT_DIR = "log_claude_54"
CSV_FILE = os.path.join(OUTPUT_DIR, "results.csv")
RAW_FILE = os.path.join(OUTPUT_DIR, "raw.txt")

os.makedirs(OUTPUT_DIR, exist_ok=True)

repos = [
"https://github.com/yrcong/RelTR",
"https://github.com/rahulvigneswaran/Lottery-Ticket-Hypothesis-in-Pytorch",
"https://github.com/henryzhongsc/gnn_editing",
"https://github.com/PriorLabs/TabPFN",
"https://github.com/fmi-basel/neural-decoding-RSNN",
"https://github.com/peng-gao-lab/p4control",
"https://github.com/RutgersCSSystems/crossprefetch-asplos24-artifacts",
"https://github.com/wenxiwang/SymMC-Tool",
"https://github.com/sumonbis/Fairify",
"https://github.com/EngineeringSoftware/exli",
"https://github.com/uiuc-arc/sixthsense",
"https://github.com/uiuc-arc/probfuzz",
"https://github.com/seal-research/gluetest",
"https://github.com/uiuc-arc/flex",
"https://github.com/xlab-uiuc/acto",
"https://github.com/wonglkd/Baleen-FAST24",
"https://github.com/iaoing/Silhouette",
"https://github.com/anvil-verifier/anvil",
"https://github.com/tinoryj/ELECT",
"https://github.com/snu-csl/rfuse",
"https://github.com/sbu-fsl/Metis",
"https://github.com/facebook/zstd",
"https://github.com/jqlang/jq",
"https://github.com/ponylang/ponyc",
"https://github.com/catchorg/Catch2",
"https://github.com/fmtlib/fmt",
"https://github.com/nlohmann/json",
"https://github.com/simdjson/simdjson",
"https://github.com/yhirose/cpp-httplib",
"https://github.com/cli/cli",
"https://github.com/grpc/grpc-go",
"https://github.com/zeromicro/go-zero",
"https://github.com/alibaba/fastjson2",
"https://github.com/elastic/logstash",
"https://github.com/mockito/mockito",
"https://github.com/anuraghazra/github-readme-stats",
"https://github.com/axios/axios",
"https://github.com/expressjs/express",
"https://github.com/iamkun/dayjs",
"https://github.com/Kong/insomnia",
"https://github.com/sveltejs/svelte",
"https://github.com/BurntSushi/ripgrep",
"https://github.com/clap-rs/clap",
"https://github.com/nushell/nushell",
"https://github.com/serde-rs/serde",
"https://github.com/sharkdp/bat",
"https://github.com/sharkdp/fd",
"https://github.com/rayon-rs/rayon",
"https://github.com/tokio-rs/bytes",
"https://github.com/tokio-rs/tokio",
"https://github.com/tokio-rs/tracing",
"https://github.com/darkreader/darkreader",
"https://github.com/mui/material-ui",
"https://github.com/vuejs/core"
]

# ===== CLIENT =====
client = OpenAI(
    base_url=FORGE_BASE_URL,
    api_key=FORGE_API_KEY,
)


def model_candidates(model_name):
    candidates = []

    def add(value):
        if value and value not in candidates:
            candidates.append(value)

    add(model_name)

    marker = "accounts/fireworks/models/"
    if marker in model_name:
        tail = model_name.split(marker, 1)[1]
        add(f"Fireworks/{tail}")
        add(f"fireworks/{tail}")

    # Normalize provider capitalization if needed.
    if model_name.startswith("fireworks/"):
        add("Fireworks/" + model_name.split("/", 1)[1])
    if model_name.startswith("Fireworks/"):
        add("fireworks/" + model_name.split("/", 1)[1])

    return candidates


MODEL_CANDIDATES = model_candidates(MODEL_NAME)
ACTIVE_MODEL = MODEL_CANDIDATES[0]


def request_hardware_estimate(prompt):
    global ACTIVE_MODEL

    last_error = None
    candidates = [ACTIVE_MODEL] + [m for m in MODEL_CANDIDATES if m != ACTIVE_MODEL]

    for candidate in candidates:
        try:
            completion = client.chat.completions.create(
                model=candidate,
                messages=[
                    {"role": "system", "content": "You estimate hardware requirements."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0
            )
            if ACTIVE_MODEL != candidate:
                print(f"Switched model to: {candidate}")
            ACTIVE_MODEL = candidate
            return completion
        except Exception as e:
            last_error = e
            # Only try alternate IDs for model-id format issues.
            if "invalid_provider" not in str(e).lower() and "model" not in str(e).lower():
                raise

    raise last_error

# ===== CLEAN JSON =====
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

print(f"Using model: {MODEL_NAME}")
if len(MODEL_CANDIDATES) > 1:
    print("Model fallback candidates:", ", ".join(MODEL_CANDIDATES[1:]))

# ===== LOOP =====
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
        completion = request_hardware_estimate(prompt)

        response_text = completion.choices[0].message.content

        # save raw
        with open(RAW_FILE, "a") as f:
            f.write(f"{repo}\n{response_text}\n{'='*50}\n")

        cleaned = clean_json(response_text)
        parsed = json.loads(cleaned)

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