#!/bin/bash
# Hook `stop`: se o resume.md ficou para trás do código, devolve um followup_message ao agente.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
cd "$(dirname "$0")/../.." || { echo '{}'; exit 0; }
python3 scripts/resume.py hook 2>/dev/null || echo '{}'
