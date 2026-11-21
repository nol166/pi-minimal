# Sourced by demo.tape (hidden): a throwaway home with made-up extensions and skills,
# so the recording shows none of your own. The real pi is launched; its placeholder
# model is never called, because the demo types no prompt.
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REAL_AGENT="${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}"
DEMO="$(cd "$(mktemp -d)" && pwd -P)"
export HOME="$DEMO/home" PI_CODING_AGENT_DIR="$DEMO/home/.pi/agent" PI_MINIMAL_STATE="$DEMO/state.json"
A="$PI_CODING_AGENT_DIR"
mkdir -p "$A/extensions/pi-web-access" "$A/bin" "$HOME/code/api/.git"
for ext in pi-web-access/index git-guard token-meter; do
  echo 'export default function () {}' > "$A/extensions/$ext.ts"
done
skill() { mkdir -p "$1"; printf -- '---\ndescription: demo\n---\n' > "$1/SKILL.md"; }
skill "$A/skills/release-notes"
skill "$A/skills/code-review"
skill "$HOME/code/api/.pi/skills/db-migrations"
# no trust prompt for the demo project, and a model so pi starts without a warning
cat > "$A/settings.json" <<'JSON'
{"defaultProjectTrust": "always", "defaultProvider": "local", "defaultModel": "qwen-3.8-flash-next"}
JSON
cat > "$A/models.json" <<'JSON'
{"providers": {"local": {"baseUrl": "http://127.0.0.1:11434/v1", "api": "openai-completions",
  "apiKey": "demo", "models": [{"id": "qwen-3.8-flash-next", "name": "Qwen3.8 Flash Next",
  "contextWindow": 131072, "maxTokens": 8192}]}}}
JSON
# reuse pi's fd and rg rather than letting it download them into the throwaway home
for tool in fd rg; do
  [ -e "$REAL_AGENT/bin/$tool" ] && ln -s "$REAL_AGENT/bin/$tool" "$A/bin/$tool"
done
pi-minimal() { python3 "$REPO/pi_minimal.py" "$@"; }
cd "$HOME/code/api"
export PS1='\[\033[2m\]~/code/api\[\033[0m\] $ '
