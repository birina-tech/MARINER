"""
llm_controller.py (backend version)

Same provider dispatch as the original MARINER desktop app. Changes for
MARINER_2 / HuggingFace:

1. The system prompt no longer lives inline — it's imported from
   prompts.PROMPT_REGISTRY, so a different prompt can be selected per
   coordinator instance (this is the "choice of different server prompt"
   from the roadmap) without touching this file.
2. API keys are still read from os.environ — on HF Spaces these come from
   Settings -> Repository secrets, not from a Qt dialog. Nothing else about
   the key-handling needed to change.
3. 'ollama' is kept for local development but will not work inside a Space
   unless you also run an Ollama server in the same container — free CPU
   Spaces cannot serve a 70B model at any usable speed. Don't select it
   in the deployed app.
4. Added 'huggingface' as an OpenAI-compatible provider slot, pointed at
   HF's Inference Providers router, for when you want to move off a
   commercial API and use an HF-hosted open model instead. Verify the
   exact endpoint/model id you want at the time you wire this up, since
   HF's hosted-model catalog changes.
"""
import requests
import json
import os
import numpy as np

from prompts import PROMPT_REGISTRY


class LLMCoordinator:
    """Coordinates maneuver commands for all ships via an LLM call."""

    PROVIDERS = {
        'ollama': {
            'name': 'Ollama (local dev only)',
            'url': 'http://localhost:11434/api/chat',
            'models': ['llama3', 'llama3.1:70b', 'qwen2.5:72b', 'mistral'],
            'default_model': 'llama3',
            'needs_key': False
        },
        'openai': {
            'name': 'OpenAI GPT-4o',
            'url': 'https://api.openai.com/v1/chat/completions',
            'models': ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo'],
            'default_model': 'gpt-4o',
            'needs_key': True,
            'key_env': 'OPENAI_API_KEY'
        },
        'anthropic': {
            'name': 'Anthropic Claude',
            'url': 'https://api.anthropic.com/v1/messages',
            'models': ['claude-sonnet-4-20250514', 'claude-3-5-sonnet-20241022'],
            'default_model': 'claude-sonnet-4-20250514',
            'needs_key': True,
            'key_env': 'ANTHROPIC_API_KEY'
        },
        'groq': {
            'name': 'Groq (fast, free tier)',
            'url': 'https://api.groq.com/openai/v1/chat/completions',
            'models': ['llama-3.3-70b-versatile', 'llama-3.1-70b-versatile', 'mixtral-8x7b-32768'],
            'default_model': 'llama-3.3-70b-versatile',
            'needs_key': True,
            'key_env': 'GROQ_API_KEY'
        },
        'deepseek': {
            'name': 'DeepSeek (cheap)',
            'url': 'https://api.deepseek.com/v1/chat/completions',
            'models': ['deepseek-chat', 'deepseek-reasoner'],
            'default_model': 'deepseek-chat',
            'needs_key': True,
            'key_env': 'DEEPSEEK_API_KEY'
        },
        'openrouter': {
            'name': 'OpenRouter (many models)',
            'url': 'https://openrouter.ai/api/v1/chat/completions',
            'models': ['meta-llama/llama-3.1-70b-instruct', 'anthropic/claude-3.5-sonnet'],
            'default_model': 'meta-llama/llama-3.1-70b-instruct',
            'needs_key': True,
            'key_env': 'OPENROUTER_API_KEY'
        },
        'huggingface': {
            # OpenAI-compatible router for HF-hosted models. Check current
            # docs at https://huggingface.co/docs/inference-providers before
            # relying on this — endpoint/model naming has changed before.
            'name': 'Hugging Face Inference (OpenAI-compatible router)',
            'url': 'https://router.huggingface.co/v1/chat/completions',
            'models': ['meta-llama/Llama-3.3-70B-Instruct', 'Qwen/Qwen2.5-72B-Instruct'],
            'default_model': 'meta-llama/Llama-3.3-70B-Instruct',
            'needs_key': True,
            'key_env': 'HF_TOKEN'
        },
    }

    def __init__(self, provider='groq', model=None, api_key=None, prompt_name='vts_default'):
        self.provider = provider
        config = self.PROVIDERS.get(provider, self.PROVIDERS['groq'])
        self.url = config['url']
        self.model = model or config['default_model']
        self.needs_key = config['needs_key']

        if api_key:
            self.api_key = api_key
        elif config.get('key_env'):
            self.api_key = os.environ.get(config['key_env'], '')
        else:
            self.api_key = None

        self.prompt_name = prompt_name
        self.system_prompt = PROMPT_REGISTRY[prompt_name]

        self.last_status = None
        self.last_error = None

    def set_prompt(self, prompt_name):
        """Swap the system prompt at runtime without recreating the coordinator."""
        self.system_prompt = PROMPT_REGISTRY[prompt_name]
        self.prompt_name = prompt_name

    def test_connection(self):
        """Check connectivity/credentials for the currently selected provider."""
        try:
            if self.provider == 'ollama':
                r = requests.get('http://localhost:11434/api/tags', timeout=5)
                if r.status_code == 200:
                    models = r.json().get('models', [])
                    model_names = [m.get('name', '') for m in models]
                    if any(self.model in m for m in model_names):
                        return True, f"Ollama is running, model {self.model} is available"
                    return False, f"Model {self.model} not found. Available: {', '.join(model_names[:5])}"
                return False, "Ollama returned an error"

            elif self.provider == 'anthropic':
                if not self.api_key:
                    return False, "API key is not set"
                headers = {
                    'x-api-key': self.api_key,
                    'anthropic-version': '2023-06-01'
                }
                payload = {
                    'model': self.model,
                    'max_tokens': 10,
                    'messages': [{'role': 'user', 'content': 'Hi'}]
                }
                r = requests.post(self.url, json=payload, headers=headers, timeout=10)
                if r.status_code == 200:
                    return True, "Connection to Anthropic successful"
                return False, f"Error {r.status_code}: {r.text[:100]}"

            else:
                if not self.api_key:
                    return False, "API key is not set"
                headers = {'Authorization': f'Bearer {self.api_key}'}
                payload = {
                    'model': self.model,
                    'messages': [{'role': 'user', 'content': 'Hi'}],
                    'max_tokens': 10
                }
                r = requests.post(self.url, json=payload, headers=headers, timeout=10)
                if r.status_code == 200:
                    return True, f"Connection to {self.provider} successful"
                return False, f"Error {r.status_code}: {r.text[:100]}"

        except requests.exceptions.ConnectionError:
            return False, f"No connection to {self.provider}. Check internet/service."
        except Exception as e:
            return False, f"Error: {str(e)[:100]}"

    def format_analysis_table(self, ships, collision_data):
        return json.dumps(collision_data, indent=2, ensure_ascii=False)

    def _call_openai_compatible(self, user_message):
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}'
        }
        payload = {
            'model': self.model,
            'messages': [
                {'role': 'system', 'content': self.system_prompt},
                {'role': 'user', 'content': user_message}
            ],
            'temperature': 0.2,
            'response_format': {'type': 'json_object'}
        }
        response = requests.post(self.url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content']

    def _call_anthropic(self, user_message):
        headers = {
            'Content-Type': 'application/json',
            'x-api-key': self.api_key,
            'anthropic-version': '2023-06-01'
        }
        payload = {
            'model': self.model,
            'max_tokens': 1024,
            'temperature': 0.2,
            'system': self.system_prompt,
            'messages': [{'role': 'user', 'content': user_message}]
        }
        response = requests.post(self.url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()['content'][0]['text']

    def _call_ollama(self, user_message):
        payload = {
            'model': self.model,
            'messages': [
                {'role': 'system', 'content': self.system_prompt},
                {'role': 'user', 'content': user_message}
            ],
            'stream': False,
            'format': 'json',
            'options': {'temperature': 0.2}
        }
        response = requests.post(self.url, json=payload, timeout=60)
        response.raise_for_status()
        return response.json()['message']['content']

    def get_coordinated_commands(self, ships, collision_data):
        """
        Blocking call to the LLM. In main.py this is run via
        asyncio.to_thread(...) so it doesn't stall the simulation loop.
        """
        content = None

        if not collision_data:
            return {
                "vessel_commands": {
                    ship.name: {
                        "rudder_deg": 0,
                        "rpm_percent": getattr(ship, 'cruise_rpm', ship.rpm_cmd),
                        "reasoning": "No threats"
                    }
                    for ship in ships if getattr(ship, 'llm_controlled', False)
                }
            }

        table_text = self.format_analysis_table(ships, collision_data)
        user_message = (
            f"Coordinate maneuvers for all vessels based on this analysis:\n\n"
            f"{table_text}\n\n"
            f"Generate commands ONLY for vessels with llm_controlled true; the others are "
            f"traffic you cannot command. "
            f"For autopilot ships use course_deg or resume_route. "
            f"For manual ships use rudder_deg and rpm_percent."
        )

        try:
            if self.provider == 'ollama':
                content = self._call_ollama(user_message)
            elif self.provider == 'anthropic':
                content = self._call_anthropic(user_message)
            else:
                content = self._call_openai_compatible(user_message)

            content = content.replace("```json", "").replace("```", "").strip()
            commands = json.loads(content)
            self.last_status = 'ok'
            self.last_error = None
            return commands

        except Exception as e:
            error_msg = str(e)
            self.last_status = 'error'
            self.last_error = error_msg
            print(f"LLM Coordinator Error ({self.provider}): {error_msg}")
            if content:
                print(f"Raw content (first 300 chars): {content[:300]}")
            else:
                print("Raw content: None (request failed before response)")

            return {
                "vessel_commands": {
                    ship.name: {
                        "rudder_deg": 0,
                        "rpm_percent": ship.rpm_cmd,
                        "reasoning": f"LLM Error: {error_msg[:50]}"
                    }
                    for ship in ships if getattr(ship, 'llm_controlled', False)
                }
            }

    def apply_commands(self, ships, commands):
        if not commands:
            print("No commands received from LLM")
            return

        vessel_commands = None
        if isinstance(commands, dict):
            if "vessel_commands" in commands:
                vessel_commands = commands["vessel_commands"]
            else:
                ship_names = [s.name for s in ships]
                if any(name in commands for name in ship_names):
                    vessel_commands = commands
                else:
                    print(f"Unexpected format. Keys: {list(commands.keys())}")
                    return

        if not vessel_commands:
            print(f"No vessel commands found. Type: {type(commands)}")
            return

        for ship in ships:
            if not getattr(ship, 'llm_controlled', False):
                continue   # only vessels in LLM mode may be commanded by the LLM
            if ship.name not in vessel_commands:
                print(f"Warning: {ship.name} not found in LLM commands")
                continue

            cmd = vessel_commands[ship.name]
            reasoning = cmd.get("reasoning", "No reasoning provided")

            autopilot_enabled = getattr(ship, 'autopilot_enabled', False)
            autopilot = getattr(ship, 'autopilot', None)

            if autopilot_enabled and autopilot is not None:
                if cmd.get('resume_route', False):
                    autopilot.resume_route()
                    ship.llm_decision = cmd
                    ship.llm_reasoning = reasoning
                    print(f"[LLM->AP] {ship.name}: RESUME ROUTE - {reasoning[:60]}")
                    continue

                if 'course_deg' in cmd and cmd['course_deg'] is not None:
                    course = cmd['course_deg']
                    if course < 0:
                        autopilot.resume_route()
                        print(f"[LLM->AP] {ship.name}: RESUME (via negative course)")
                    else:
                        course = course % 360
                        autopilot.set_hold_course(course)
                        ship.llm_decision = cmd
                        ship.llm_reasoning = reasoning
                        print(f"[LLM->AP] {ship.name}: HOLD COURSE {course:.1f} deg - {reasoning[:60]}")
                    continue

                if 'rudder_deg' in cmd:
                    current_heading = ship.get_heading_deg()
                    autopilot.set_hold_course(current_heading)
                    ship.rudder_cmd = np.clip(cmd['rudder_deg'], -35, 35)
                    ship.llm_decision = cmd
                    ship.llm_reasoning = reasoning
                    print(f"[LLM->AP] {ship.name}: direct rudder {cmd['rudder_deg']} deg (fallback)")
                    continue

                autopilot.resume_route()
                print(f"[LLM->AP] {ship.name}: unrecognized command, resuming route")
                continue

            rudder = cmd.get("rudder_deg", 0)
            rpm = cmd.get("rpm_percent", ship.rpm_cmd)   # not given: keep the current order

            rudder = np.clip(rudder, -35, 35)
            rpm = np.clip(rpm, 0, 100)

            ship.apply_llm_command(rudder, rpm)
            ship.llm_decision = cmd
            ship.llm_reasoning = reasoning

            if 'course_deg' in cmd and cmd['course_deg'] is not None:
                new_course = cmd['course_deg'] % 360
                ship.set_base_heading(new_course)
                current_heading = ship.get_heading_deg()
                turn_angle = (new_course - current_heading + 180) % 360 - 180
                ship.rudder_cmd = np.clip(turn_angle * 2, -35, 35)
                print(f"[LLM] {ship.name}: course {new_course:.1f} deg (manual)")
