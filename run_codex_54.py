from openai import OpenAI
import json
import os
import time

# ===== CONFIG =====
FORGE_API_KEY = os.getenv("FORGE_API_KEY")

OUTPUT_DIR = "log_codex_54"
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
    base_url="https://api.forge.tensorblock.co/v1",
    api_key=FORGE_API_KEY,
)

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

# ===== LOOP =====
for repo in repos:
    print(f"\nProcessing: {repo}")

    prompt = f"""
Given this GitHub repository:
{repo}

Estimate:
- CPU (cores)
- RAM (GB)
- Disk (GB)
- GPU (true/false)
- GPU memory (GB)

Return ONLY raw JSON.
"""

    try:
        completion = client.chat.completions.create(
            model="OpenAI/gpt-4o",
            messages=[
                {"role": "system", "content": "You estimate hardware requirements."},
                {"role": "user", "content": prompt}
            ],
            temperature=0
        )

        response_text = completion.choices[0].message.content

        # save raw
        with open(RAW_FILE, "a") as f:
            f.write(f"{repo}\n{response_text}\n{'='*50}\n")

        # parse
        cleaned = clean_json(response_text)
        parsed = json.loads(cleaned)

        cpu = parsed.get("cpu") or parsed.get("CPU") or parsed.get("cpu_cores")
        ram = parsed.get("ram") or parsed.get("RAM") or parsed.get("memory")
        disk = parsed.get("disk") or parsed.get("storage")
        gpu = parsed.get("gpu")
        gpu_memory = parsed.get("gpu_memory") or parsed.get("gpuMemory")

        with open(CSV_FILE, "a") as f:
            f.write(f"{repo},{cpu},{ram},{disk},{gpu},{gpu_memory}\n")

        print("✔ Done")

        time.sleep(1)  # avoid rate limits

    except Exception as e:
        print(f"✗ Failed: {repo}")
        print(e)