"""
prompts/__init__.py

Registry of available "server prompts". To add a new one:
  1. Create prompts/vts_<name>.py with a SYSTEM_PROMPT string.
  2. Import it below and add it to PROMPT_REGISTRY under a short key.
  3. Select it via LLMCoordinator(..., prompt_name='<key>') or
     coordinator.set_prompt('<key>') at runtime, e.g. from a
     {"type": "set_llm_prompt", "prompt": "<key>"} WebSocket command.
"""
from prompts.vts_default import SYSTEM_PROMPT as VTS_DEFAULT

PROMPT_REGISTRY = {
    'vts_default': VTS_DEFAULT,
}
