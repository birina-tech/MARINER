"""
llm_controller.py
Universal LLM coordinator powered by LiteLLM.
"""
import json
import os
import litellm
from agent_prompts import AUTOPILOT_SYSTEM_PROMPT

# Optional: Suppress litellm telemetry if you prefer
litellm.telemetry = False

class LLMCoordinator:
    PROVIDERS = {
        'ollama': {
            'name': 'Ollama (локально)',
            'prefix': 'ollama/',
            'models': ['llama3', 'llama3.1:70b', 'qwen2.5:72b', 'mistral', 'deepseek-r1'],
            'default_model': 'llama3',
            'needs_key': False
        },
        'openai': {
            'name': 'OpenAI GPT-4o',
            'prefix': 'openai/',
            'models': ['gpt-4o', 'gpt-4o-mini'],
            'default_model': 'gpt-4o',
            'needs_key': True,
            'key_env': 'OPENAI_API_KEY'
        },
        'anthropic': {
            'name': 'Anthropic Claude',
            'prefix': 'anthropic/',
            'models': ['claude-haiku-4-5-20251001', 'claude-3-5-sonnet-20241022'],
            'default_model': 'claude-haiku-4-5-20251001',
            'needs_key': True,
            'key_env': 'ANTHROPIC_API_KEY'
        },
        'gemini': {
            'name': 'Google Gemini',
            'prefix': 'gemini/',
            'models': ['gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-2.5-flash'],
            'default_model': 'gemini-1.5-flash',
            'needs_key': True,
            'key_env': 'GEMINI_API_KEY'
        },
        'qwen': {
            'name': 'Alibaba Qwen',
            'prefix': 'hosted_vllm/', # LiteLLM routing for compatible endpoints
            'models': ['qwen3.7-plus'],
            'default_model': 'qwen3.7-plus',
            'needs_key': True,
            'key_env': 'QWEN_API_KEY',
            'api_base': 'https://dashscope.aliyuncs.com/compatible-mode/v1'
        },
        'groq': {
            'name': 'Groq (быстро, бесплатно)',
            'prefix': 'groq/',
            'models': ['llama-3.3-70b-versatile', 'mixtral-8x7b-32768'],
            'default_model': 'llama-3.3-70b-versatile',
            'needs_key': True,
            'key_env': 'GROQ_API_KEY'
        }
    }

    def __init__(self, provider='ollama', model=None, api_key=None):
        self.provider = provider
        config = self.PROVIDERS.get(provider, self.PROVIDERS['ollama'])

        # LiteLLM requires standard prefixes (e.g., "gemini/gemini-1.5-flash")
        raw_model = model or config['default_model']
        self.model = f"{config.get('prefix', '')}{raw_model}"
        
        self.api_base = config.get('api_base')
        self.last_status = None
        self.last_error = None

        # Set environment variables for LiteLLM to pick up automatically
        if api_key and config.get('key_env'):
            os.environ[config['key_env']] = api_key

    def test_connection(self):
        """Provider connection check using LiteLLM."""
        try:
            response = litellm.completion(
                model=self.model,
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=10,
                api_base=self.api_base
            )
            return True, f"Connection to {self.provider} successful!"
        except Exception as e:
            return False, f"Connection Error: {str(e)[:100]}"

    def get_ego_command(self, collision_data): 
        """Sends a request on behalf of the ego vessel using LiteLLM."""
        if not collision_data or not collision_data.get('pairs'):
            return {"rudder_deg": 0, "rpm_percent": 50, "reasoning": "No threats"}

        user_message = (f"Determine the maneuver for your vessel based on this telemetry and position and heading of other vessels:\n\n"
                        f"{json.dumps(collision_data, indent=2)}\n\n"
                        f"Generate your command.")
        
        messages = [
            {"role": "system", "content": AUTOPILOT_SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ]

        try:
            # LiteLLM handles all formatting, headers, and routing!
            response = litellm.completion(
                model=self.model,
                messages=messages,
                temperature=0.1,
                api_base=self.api_base,
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content
            
            # Clean up potential markdown formatting just in case
            content = content.replace("```json", "").replace("```", "").strip()
            command = json.loads(content)
            
            self.last_status = 'ok'
            return command

        except Exception as e:
            self.last_status = 'error'
            self.last_error = str(e)
            return {"rudder_deg": 0, "rpm_percent": 50, "reasoning": f"Error: {str(e)[:50]}"}