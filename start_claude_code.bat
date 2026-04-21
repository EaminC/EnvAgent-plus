@echo off
setlocal

if "%ANTHROPIC_AUTH_TOKEN%"=="" (
  echo ANTHROPIC_AUTH_TOKEN is not set.
  echo Run: set ANTHROPIC_AUTH_TOKEN=your_forge_key
  exit /b 1
)

if "%ANTHROPIC_BASE_URL%"=="" set ANTHROPIC_BASE_URL=https://api.forge.tensorblock.co
if "%ANTHROPIC_MODEL%"=="" set ANTHROPIC_MODEL=Fireworks/accounts/fireworks/models/qwen3-coder-480b-a35b-instruct
if "%ANTHROPIC_SMALL_FAST_MODEL%"=="" set ANTHROPIC_SMALL_FAST_MODEL=Gemini/models/gemini-2.5-flash

claude %*
