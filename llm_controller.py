"""
llm_controller.py
Universal LLM coordinator powered by LiteLLM.
"""
import json
import os
import litellm
from agent_prompts import AUTOPILOT_SYSTEM_PROMPT

# Suppress litellm telemetry
litellm.telemetry = False
# SAFETY VALVE: Drop unsupported parameters instead of crashing
litellm.drop_params = True


class LLMCoordinator:
    PROVIDERS = {
        'ollama': {
            'name': 'Ollama (local)',
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
            'models': ['gemini/gemini-3.1-flash-lite', 'gemini/gemini-flash-lite'],
            'default_model': 'gemini/gemini-3.1-flash-lite',
            'needs_key': True,
            'key_env': 'GEMINI_API_KEY'
        },
        'qwen': {
            'name': 'Alibaba Qwen (US)',
            'prefix': 'dashscope/', 
            'models': ['qwen-plus', 'qwen-turbo', 'qwen-max'],
            'default_model': 'qwen-plus',
            'needs_key': True,
            'key_env': 'DASHSCOPE_API_KEY',
            # Set the explicit US endpoint here:
            'api_base': 'https://dashscope-us.aliyuncs.com/compatible-mode/v1'
        },
        'groq': {
            'name': 'Groq (fast, free)',
            'prefix': 'groq/',
            'models': ['llama-3.3-70b-versatile', 'mixtral-8x7b-32768'],
            'default_model': 'llama-3.3-70b-versatile',
            'needs_key': True,
            'key_env': 'GROQ_API_KEY'
        },
        'deepseek': {
            'name': 'DeepSeek Cloud API',
            'prefix': 'deepseek/',
            'models': ['deepseek-chat', 'deepseek-reasoner'],
            'default_model': 'deepseek-chat',
            'needs_key': True,
            'key_env': 'DEEPSEEK_API_KEY'
        }
    }

    def __init__(self, provider='ollama', model=None, api_key=None):
        self.provider = provider
        config = self.PROVIDERS.get(provider, self.PROVIDERS['ollama'])

        # 1. Get raw model name or default
        selected_model = model or config['default_model']
        
        # 2. Safely apply prefix without duplicating it
        prefix = config.get('prefix', '')
        if prefix and not selected_model.startswith(prefix):
            self.model = f"{prefix}{selected_model}"
        else:
            self.model = selected_model

        self.api_base = config.get('api_base')
        self.last_status = None
        self.last_error = None

        if config.get('key_env'):
            if api_key:
                os.environ[config['key_env']] = api_key
            else:
                os.environ.pop(config['key_env'], None)

    def test_connection(self):
        """Provider connection check using LiteLLM."""
        response = None  
        try:
            config = self.PROVIDERS.get(self.provider, {})
            env_key = config.get('key_env')
            
            if env_key and not os.environ.get(env_key):
                return False, f"Connection Error: API Key for {self.provider} is empty or missing."

            kwargs = {
                "model": self.model,
                "messages": [{"role": "user", "content": "Hi"}]
            }
            if self.api_base:
                kwargs["api_base"] = self.api_base

            response = litellm.completion(**kwargs)
            return True, f"Connection to {self.provider} successful!"
        except Exception as e:
            return False, f"Connection Error: {str(e)}"
        
    def get_ego_command(self, collision_data): 
        if not collision_data or not collision_data.get('pairs'):
            return {"rudder_deg": 0, "rpm_percent": 50, "reasoning": "No threats"}

        user_message = (f"Determine the maneuver for your vessel based on this telemetry:\n\n"
                        f"{json.dumps(collision_data, indent=2)}\n\n"
                        f"Generate your command.")
        
        messages = [
            {"role": "system", "content": AUTOPILOT_SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ]

        response = None  # <-- Add this initialization safe-guard
        try:
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": 0.1,
                "response_format": {"type": "json_object"}
            }
            if self.api_base:
                kwargs["api_base"] = self.api_base

            response = litellm.completion(**kwargs)
            
            content = response.choices[0].message.content
            content = content.replace("```json", "").replace("```", "").strip()
            command = json.loads(content)
            
            self.last_status = 'ok'
            return command

        except Exception as e:
            self.last_status = 'error'
            self.last_error = str(e)
            return {"rudder_deg": 0, "rpm_percent": 50, "reasoning": f"API Error: {str(e)}"}