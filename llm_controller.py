"""
llm_controller.py
Универсальный LLM-координатор с поддержкой локальных и онлайн моделей.
"""
import requests
import json
import os
import numpy as np


class LLMCoordinator:
    # Providers' configuration
    PROVIDERS = {
        'ollama': {
            'name': 'Ollama (локально)',
            'url': 'http://localhost:11434/api/chat',
            'models': ['llama3', 'llama3.1:70b', 'qwen2.5:72b', 'mistral'],
            'default_model': 'llama3',
            'needs_key': False
        },
        'deepseek': {
            'name': 'DeepSeek (дёшево)',
            'url': 'https://api.deepseek.com/v1/chat/completions',
            'models': ['deepseek-chat', 'deepseek-reasoner'],
            'default_model': 'deepseek-chat',
            'needs_key': True,
            'key_env': 'DEEPSEEK_API_KEY'
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
            'models': ['claude-haiku-4-5-20251001', 'claude-sonnet-4-20250514', 'claude-3-5-sonnet-20241022'],
            'default_model': 'claude-haiku-4-5-20251001',
            'needs_key': True,
            'key_env': 'ANTHROPIC_API_KEY'
        },
        'gemini': {
            'name': 'Google Gemini',
            'url': 'https://generativelanguage.googleapis.com/v1beta/models/',
            'models': ['gemini-2.5-flash', 'gemini-1.5-pro'],
            'default_model': 'gemini-2.5-flash',
            'needs_key': True,
            'key_env': 'GEMINI_API_KEY'
        },
        'qwen': {
            'name': 'Alibaba Qwen',
            'url': 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions',
            'models': ['qwen3.7-plus', 'qwen-max'],
            'default_model': 'qwen3.7-plus',
            'needs_key': True,
            'key_env': 'QWEN_API_KEY'
        },
        'groq': {
            'name': 'Groq (быстро, бесплатно)',
            'url': 'https://api.groq.com/openai/v1/chat/completions',
            'models': ['llama-3.3-70b-versatile', 'llama-3.1-70b-versatile', 'mixtral-8x7b-32768'],
            'default_model': 'llama-3.3-70b-versatile',
            'needs_key': True,
            'key_env': 'GROQ_API_KEY'
        }
    }

    def __init__(self, provider='ollama', model=None, api_key=None):
        self.provider = provider
        config = self.PROVIDERS.get(provider, self.PROVIDERS['ollama'])

        self.url = config['url']
        self.model = model or config['default_model']
        self.needs_key = config['needs_key']

        # API key check
        if api_key:
            self.api_key = api_key
        elif config.get('key_env'):
            self.api_key = os.environ.get(config['key_env'], '')
        else:
            self.api_key = None

        self.system_prompt = """You are an AI Autopilot for a specific marine vessel (the "ego vessel").
You receive your current telemetry and a list of other vessels in your vicinity and thier current coordinates and heading.
Your first priority is safety following COLREGs rules. 
Your second priority, if vessel is safe, is to maintain your initial course.

INPUT FORMAT (JSON):
{
  "name": "Ship_1",
  "current_x": 1200.5,
  "current_y": 3400.2,
  "base_x": 1000.0,
  "base_y": 3000.0,
  "current_heading_deg": 45,
  "base_heading_deg": 45,
  "heading_diff_deg": 15,
  "speed_ms": 5.0,
  "current_rudder": 0,
  "current_rpm": 50,
  "status": "MUST_YIELD" | "HOLD_COURSE" | "RETURN_TO_COURSE",
  "no_left_turn": true | false,
  "in_maneuver": true | false,
  "pairs": [
    {
      "other_ship": "Ship_2",
      "rule": "14" | "15" | "13" | "17.2",
      "role": "GIVE_WAY" | "STAND_ON" | "BOTH_ALTER",
      "cpa_m": 500,
      "tcpa_s": 120,
      "crosses_ahead": "Ship_2 crosses Ship_1 ahead" | null
    }
  ]
}

OUTPUT FORMAT (strict JSON only, no extra text):
{
  "rudder_deg": 15,
  "rpm_percent": 50,
  "reasoning": "Brief explanation of your maneuver based on the rules."
}



Actions (follow strictly unless safety is at risk):

1. STATUS PRIORITY:
   - If status == "MUST_YIELD" -> you MUST maneuver (change rudder and/or RPM).
   - If status == "HOLD_COURSE" -> keep rudder=0, rpm=50 (maintain course and speed).
   - If a ship is MUST_YIELD for one pair but HOLD_COURSE for another -> choose MUST_YIELD.

2. MANEUVER DIRECTION (HARD RULE) used when there are other ships nearby:
   - ALWAYS prefer STARBOARD turn (positive rudder).
   - CRITICAL CONVERGENCE (Rule 17.2 / Emergency / CPA < 1000 meters): YOU MUST TURN STARBOARD. Port turn (negative rudder) is STRICTLY FORBIDDEN in emergencies.
      -- The vessel may take action to avoid collision by her manoeuvre alone, 
         as soon as it becomes apparent to her that the other vessel that is required to keep out 
         of the way is not taking appropriate action in compliance with these Rules.
   - If no_left_turn == true -> rudder_deg MUST be >= 0. Negative values are FORBIDDEN.
   - If status == "HOLD_COURSE" -> rudder_deg MUST be 0, recomended rpm_percent MUST be 50
   - If other vessel is in front with simular speed consider to slow down to create a larger distance between two vessels. 
   - NO MANEUVERS ALLOWED for stand-on vessels.
   - If status == "MUST_YIELD" -> rudder_deg MUST be >= 0 (STARBOARD turn ONLY). NEGATIVE RUDDER IS STRICTLY FORBIDDEN.

3. MANEUVER MAGNITUDE for some rules:
   - Under Rule 14 for Head-on Situation: rudder should be from 15 to 25 deg starboard.
   - Under Rule 15 for Crossing Situation: rudder should be from 15 to 25 deg starboard.
   - Under Rule 13 for overtaking: rudder should be from 10 to 20 deg away from overtaken vessel.
   - Under Rule 17.2 for critical convergence / emergency: rudder should be from 20 to 35 deg STARBOARD. Reduce RPM to at least 30-40% (or less) if CPA < 500 meters.
   -- In other situations apply smooth changes: max 15 deg rudder change per step.

4. ECO-MODE:
   - Prefer rudder changes over RPM changes.
   - Keep RPM at 50% unless CPA < 1000m or emergency.
   - If reducing RPM: min 30%, never 0%.

5. NO MANEUVER NEEDED:
   - If status == "HOLD_COURSE" AND not "returning" -> output rudder=0, rpm=50.

Respond with valid JSON only. No markdown, no explanation outside JSON."""

        # Статус подключения
        self.last_status = None
        self.last_error = None

    def test_connection(self):
        """Provider connection check. Return (success, message)"""
        try:
            if self.provider == 'ollama':
                r = requests.get('http://localhost:11434/api/tags', timeout=5)
                if r.status_code == 200:
                    models = r.json().get('models', [])
                    model_names = [m.get('name', '') for m in models]
                    if any(self.model in m for m in model_names):
                        return True, f"ollama is launched, model {self.model} is available"
                    else:
                        return False, f"Model {self.model} is not accessible. Available: {', '.join(model_names[:5])}"
                else:
                    return False, "ollama returned an error"

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
                    return True, "Connection to Anthropic is sucessful"
                else:
                    return False, f"Error {r.status_code}: {r.text[:100]}"
            elif self.provider == 'gemini':
                if not self.api_key:
                    return False, "API key is not set"
                full_url = f"{self.url}{self.model}:generateContent?key={self.api_key}"
                headers = {'Content-Type': 'application/json'}
                payload = {
                    "contents": [{"parts": [{"text": "Hi"}]}],
                    "generationConfig": {"maxOutputTokens": 10}
                }
                r = requests.post(full_url, json=payload, headers=headers, timeout=10)
                if r.status_code == 200:
                    return True, "Connection to Google Gemini is successful"
                else:
                    return False, f"Error {r.status_code}: {r.text[:100]}"
            else:  # OpenAI-совместимые API
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
                    return True, f"Подключение к {self.provider} успешно"
                else:
                    return False, f"Ошибка {r.status_code}: {r.text[:100]}"

        except requests.exceptions.ConnectionError:
            return False, f"Нет соединения с {self.provider}. Проверьте интернет/запуск сервиса."
        except Exception as e:
            return False, f"Ошибка: {str(e)[:100]}"

    def format_analysis_table(self, ships, collision_data):
        """Preparing data for LLM.
        collision_data — disctionary {'ships': [...]} from collect_collision_data().
        Use JSON format — LLM resive only sctructured data.
        """
        import json
        return json.dumps(collision_data, indent=2, ensure_ascii=False)

    def _call_openai_compatible(self, user_message):
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}'
        }
        
        # Apply specific constraints for Qwen
        temp = 0.1 if self.provider == 'qwen' else 0.2
        max_t = 50 if self.provider == 'qwen' else 1024

        payload = {
            'model': self.model,
            'messages': [
                {'role': 'system', 'content': self.system_prompt},
                {'role': 'user', 'content': user_message}
            ],
            'temperature': temp,
            'max_tokens': max_t,
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
            'temperature': 0.1,
            'system': self.system_prompt,
            'messages': [{'role': 'user', 'content': user_message}]
        }
        response = requests.post(self.url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()['content'][0]['text']

    def _call_gemini(self, user_message):
        full_url = f"{self.url}{self.model}:generateContent?key={self.api_key}"
        headers = {'Content-Type': 'application/json'}
        payload = {
            "system_instruction": {
                "parts": [{"text": self.system_prompt}]
            },
            "contents": [{
                "parts": [{"text": user_message}]
            }],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 5000,
                "responseMimeType": "application/json"
            }
        }
        
        
        response = requests.post(full_url, json=payload, headers=headers, timeout=30)
        
        
        response.raise_for_status()
        data = response.json()
        
        ### use a try-except block to catch specific structural errors in the dictionary
        try:
            return data['candidates'][0]['content']['parts'][0]['text']
        except KeyError as e:
            print("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
            print(f"DEBUG GEMINI: KeyError! Google's response is missing this key: {e}")
            print("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
            raise Exception(f"Unexpected Gemini format. Check terminal for raw text.")



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


    def get_ego_command(self, collision_data): # Sends a request on behalf of the ego vessel.
        
        if not collision_data or not collision_data.get('pairs'):
            return {"rudder_deg": 0, "rpm_percent": 50, "reasoning": "No threats"}

        # Format the data for ego ship
        user_message = (f"Determine the maneuver for your vessel based on this telemetry and position and heading of other vessels:\n\n"
                        f"{json.dumps(collision_data, indent=2)}\n\n"
                        f"Generate your command.")
        
        try:
            if self.provider == 'ollama':
                content = self._call_ollama(user_message)
            elif self.provider == 'anthropic':
                content = self._call_anthropic(user_message)
            elif self.provider == 'gemini':
                content = self._call_gemini(user_message)
            else:
                # OpenAI, Groq, DeepSeek, and Qwen all use this compatible format
                content = self._call_openai_compatible(user_message)

            content = content.replace("```json", "").replace("```", "").strip()
            command = json.loads(content)
            self.last_status = 'ok'
            return command

        except Exception as e:
            self.last_status = 'error'
            self.last_error = str(e)
            return {"rudder_deg": 0, "rpm_percent": 50, "reasoning": f"Error: {str(e)[:50]}"}

