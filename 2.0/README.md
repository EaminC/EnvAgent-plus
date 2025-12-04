# EnvAgent-plus 2.0

## Automated Hardware Provisioning Tool with AI

This is the 2.0 version of EnvAgent-plus, featuring AI-driven automated hardware provisioning for Chameleon Cloud.

## Quick Start

### 1. Install Dependencies

```bash
cd /home/cc/EnvAgent-plus/2.0/src
pip install -r requirements.txt
```

### 2. Configure

Create `.env` file:

```bash
cat > .env << EOF
OPENAI_BASE_URL=https://api.forge.tensorblock.co/v1
OPENAI_API_KEY=your-api-key-here
OPENAI_MODEL=OpenAI/gpt-4o
EOF
```

### 3. Authenticate

```bash
source ../config/CHI-251467-openrc.sh
```

### 4. Run

```bash
# Use v2.0 (SDK-based, recommended)
python provision_v2.py --repo https://github.com/pytorch/examples

# Or use v1.0 (CLI-based)
python provision.py --repo https://github.com/pytorch/examples
```

## Features

- 🤖 **AI-Driven Analysis**: Automatically analyzes GitHub repositories to determine hardware requirements
- 🎯 **Smart Selection**: Two-stage AI selection for OS images and hardware resources
- ⚡ **Fast Deployment**: SDK-based implementation is 2-3x faster than CLI
- 🔄 **Full Integration**: Works seamlessly with existing EnvAgent-plus infrastructure
- 📊 **Progress Tracking**: Real-time feedback on deployment progress
- 🌐 **Network Management**: Automatic floating IP allocation for external access

## Documentation

- **[WHATS_NEW_2.0.md](../WHATS_NEW_2.0.md)** - Overview of new features
- **[README.md](src/README.md)** - Detailed user guide
- **[USAGE_EXAMPLES.md](src/USAGE_EXAMPLES.md)** - Usage examples
- **[ARCHITECTURE.md](src/ARCHITECTURE.md)** - System architecture
- **[VERSION_COMPARISON.md](src/VERSION_COMPARISON.md)** - v1.0 vs v2.0 comparison
- **[INTEGRATION_GUIDE.md](src/INTEGRATION_GUIDE.md)** - Integration guide
- **[IMPLEMENTATION_SUMMARY.md](src/IMPLEMENTATION_SUMMARY.md)** - Implementation details

## Directory Structure

```
2.0/
├── api/
│   └── forge.py                 # AI API example
├── src/
│   ├── provision.py             # v1.0 CLI-based
│   ├── provision_v2.py          # v2.0 SDK-based ⭐
│   ├── config.py                # Configuration
│   ├── ai_client.py            # AI integration
│   ├── repo_analyzer.py        # Repo analysis
│   ├── key_manager.py          # SSH keys (v1.0)
│   ├── image_selector.py       # Images (v1.0)
│   ├── resource_discovery.py   # Resources (v1.0)
│   ├── network_manager.py      # Networks (v1.0)
│   ├── reservation_manager.py  # Leases (v1.0)
│   ├── server_launcher.py      # Launch (v1.0)
│   ├── requirements.txt        # Dependencies
│   ├── env.example             # Config template
│   ├── quick_start.sh          # Quick launch
│   └── *.md                    # Documentation
└── WHATS_NEW_2.0.md            # Release notes
```

## Two Versions

### v1.0 (CLI-based) - `provision.py`
- Uses OpenStack CLI tools
- Easy to debug
- Good for learning

### v2.0 (SDK-based) - `provision_v2.py` ⭐ Recommended
- Uses OpenStack SDK
- 2-3x faster
- Better integration

## Example Usage

```bash
# Basic usage
python provision_v2.py --repo https://github.com/pytorch/examples

# Create new SSH key
python provision_v2.py --repo https://github.com/user/project --create-key

# Custom configuration
python provision_v2.py \
    --repo https://github.com/user/project \
    --lease-name ml-training \
    --server-name gpu-node-01 \
    --node-type gpu_rtx_6000

# No floating IP
python provision_v2.py \
    --repo https://github.com/user/project \
    --no-floating-ip
```

## Requirements

- Python 3.8+
- OpenStack credentials (OpenRC file)
- AI API key (OpenAI-compatible)
- Internet connection

## Support

For issues or questions:
1. Check documentation in `src/*.md`
2. Review existing `api-core/` tools in parent directory
3. Consult `envboot/osutil.py` for SDK usage

## License

MIT License

