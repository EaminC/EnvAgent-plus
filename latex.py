repos = [
    "RelTR",
    "Lottery-Ticket-Hypothesis-in-Pytorch",
    "gnn-editing",
    "TabPFN",
    "neural-decoding-RSNN",
    "p4control",
    "crossprefetch-asplos24-artifacts",
    "SymMC-Tool",
    "Fairify",
    "exli",
    "sixthsense",
    "probfuzz",
    "gluetest",
    "flex",
    "acto",
    "Baleen-FAST24",
    "Silhouette",
    "anvil",
    "ELECT",
    "rfuse",
    "Metis",
    "zstd",
    "jq",
    "ponyc",
    "Catch2",
    "fmt",
    "json",
    "simdjson",
    "cpp-httplib",
    "cli",
    "grpc-go",
    "go-zero",
    "fastjson2",
    "logstash",
    "mockito",
    "github-readme-stats",
    "axios",
    "express",
    "dayjs",
    "insomnia",
    "svelte",
    "ripgrep",
    "clap",
    "nushell",
    "serde",
    "bat",
    "fd",
    "rayon",
    "bytes",
    "tokio",
    "tracing",
    "darkreader",
    "material-ui",
    "core"
]

methods = ["Ours", "Claude Code", "Codex"]
models = ["GPT-4.1-mini", "TBD-1"]

rows_per_repo = len(methods) * len(models)

for i, repo in enumerate(repos):
    first = True
    for method in methods:
        for model in models:
            if first:
                print(f"\\multirow{{{rows_per_repo}}}{{*}}{{{repo}}} & {method} & {model} &  &  &  \\\\")
                first = False
            else:
                print(f"& {method} & {model} &  &  &  \\\\")
    if i != len(repos) - 1:
        print("\\midrule")