"""
llm_controller.py
Универсальный LLM-координатор с поддержкой локальных и онлайн моделей.
ИСПРАВЛЕНО: обработка ошибок и поддержка авторулевого.
"""
import requests
import json
import os
import numpy as np


class LLMCoordinator:
    """Координатор движения судов на базе LLM"""

    PROVIDERS = {
        'ollama': {
            'name': 'Ollama (локально)',
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
            'name': 'Groq (быстро, бесплатно)',
            'url': 'https://api.groq.com/openai/v1/chat/completions',
            'models': ['llama-3.3-70b-versatile', 'llama-3.1-70b-versatile', 'mixtral-8x7b-32768'],
            'default_model': 'llama-3.3-70b-versatile',
            'needs_key': True,
            'key_env': 'GROQ_API_KEY'
        },
        'deepseek': {
            'name': 'DeepSeek (дёшево)',
            'url': 'https://api.deepseek.com/v1/chat/completions',
            'models': ['deepseek-chat', 'deepseek-reasoner'],
            'default_model': 'deepseek-chat',
            'needs_key': True,
            'key_env': 'DEEPSEEK_API_KEY'
        },
        'openrouter': {
            'name': 'OpenRouter (много моделей)',
            'url': 'https://openrouter.ai/api/v1/chat/completions',
            'models': ['meta-llama/llama-3.1-70b-instruct', 'anthropic/claude-3.5-sonnet'],
            'default_model': 'meta-llama/llama-3.1-70b-instruct',
            'needs_key': True,
            'key_env': 'OPENROUTER_API_KEY'
        }
    }

    def __init__(self, provider='ollama', model=None, api_key=None):
        self.provider = provider
        config = self.PROVIDERS.get(provider, self.PROVIDERS['ollama'])
        self.url = config['url']
        self.model = model or config['default_model']
        self.needs_key = config['needs_key']

        if api_key:
            self.api_key = api_key
        elif config.get('key_env'):
            self.api_key = os.environ.get(config['key_env'], '')
        else:
            self.api_key = None

        self.system_prompt = """You are an AI Vessel Traffic Controller.
Your first priority is COLLISION AVOIDANCE.
Your second priority is maintaining efficient voyage (returning to route/base course when safe).

You do NOT determine COLREG rules — they are already provided in the input.
You ONLY output rudder/RPM for manual ships, or course_deg/resume_route for autopilot ships.

=== INPUT FORMAT (JSON) ===
{
 "ships": [
{
 "name": "Ship_1",
 "current_heading_deg": 45,
 "base_heading_deg": 45,
 "heading_diff_deg": 15,
 "speed_ms": 5.0,
 "current_rudder": 0,
 "current_rpm": 50,
 "status": "MUST_YIELD" | "HOLD_COURSE" | "RETURN_TO_COURSE",
 "no_left_turn": true | false,
 "in_maneuver": true | false,
 "maneuver_course_deg": 90 | null,
 "maneuver_target_course": 90 | null,
 "autopilot_enabled": true | false,
 "autopilot_mode": "ROUTE" | "HOLD" | null,
 "assigned_route": "Route_1" | null,
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
]
}

=== OUTPUT FORMAT (strict JSON only) ===
{
  "vessel_commands": {
    "Ship_1": {
      "rudder_deg": 15,
      "rpm_percent": 50,
      "reasoning": "Rule 15 give-way, turning starboard"
    },
    "Ship_2": {
      "course_deg": 90,
      "reasoning": "Avoiding collision, holding course 90° until safe"
    },
    "Ship_3": {
      "resume_route": true,
      "reasoning": "Collision avoided, resuming route"
    }
  }
}
=== MANEUVER CONTROL RULE (CRITICAL) ===
When a ship has in_maneuver == true:
- The ship is currently executing a collision avoidance maneuver
- DO NOT issue "resume_route" until the ship has reached the maneuver course
- Continue issuing the SAME course_deg until heading_diff_deg <= 5°
- You may ADJUST the course_deg if CPA/TCPA worsens, but DO NOT cancel the maneuver
- Only when heading_diff_deg <= 5° AND CPA > 1500m AND TCPA > 300s you may issue resume_route
- This prevents dangerous oscillation between maneuver and return-to-course

When a ship has in_maneuver == false:
- Analyze CPA/TCPA normally according to COLREGs
- If collision risk exists, issue course_deg to avoid it (this will set in_maneuver=true)
- If safe, you may issue resume_route or maintain current course

=== RULES FOR AUTOPILOT SHIPS (autopilot_enabled == true) ===
These ships follow a route automatically. You control them via HIGH-LEVEL commands:

1. TO AVOID COLLISION — issue a new course to hold:
   {"course_deg": <angle_0_to_359>}
   The autopilot will smoothly turn to and hold this course.
   - Prefer STARBOARD turns (increase course angle).
   - Turn magnitude: 20-45° is usually sufficient.
   - If no_left_turn == true, course_deg MUST be >= current_heading (starboard turn only).

2. WHEN SAFE TO RESUME — tell autopilot to return to route:
   {"resume_route": true}
   Issue this ONLY when:
   - DCPA > 1500m AND TCPA > 300s for all threatening pairs, OR
   - The threatening ship has clearly passed (crosses_ahead was true and now tcpa_s < 0 or very small)
   - Do NOT resume too early — wait until danger has clearly passed.

3. NEVER issue "rudder_deg" to autopilot ships — they ignore it.
   NEVER issue both "course_deg" and "resume_route" in the same command.

=== RULES FOR MANUAL/LLM SHIPS (autopilot_enabled == false) ===
These ships are controlled via rudder and RPM:

1. STATUS PRIORITY:
   - MUST_YIELD → you MUST maneuver (change rudder).
   - HOLD_COURSE → keep rudder=0, rpm=50.
   - RETURN_TO_COURSE → small rudder toward base_heading_deg.
   - If MUST_YIELD for one pair but HOLD_COURSE for another → choose MUST_YIELD.

2. MANEUVER DIRECTION:
   - ALWAYS prefer STARBOARD turn (positive rudder).
   - CRITICAL (Rule 17.2 / CPA < 1000m): STARBOARD turn MANDATORY. Port turn FORBIDDEN.
   - If no_left_turn == true → rudder_deg MUST be >= 0.
   - If MUST_YIELD → rudder_deg MUST be >= 0 (STARBOARD ONLY).

3. MANEUVER MAGNITUDE:
   - Rule 14 (head-on): 15-25° starboard.
   - Rule 15 (crossing, give-way): 15-25° starboard.
   - Rule 13 (overtaking): 10-20° away from overtaken vessel.
   - Rule 17.2 (emergency): 20-35° STARBOARD. Reduce RPM to 30-40% if CPA < 500m.
   - Max 15° rudder change per step in non-emergency.

4. RETURN TO BASE COURSE:
   - Small rudder (-10 to +10°) toward base_heading_deg.
   - If heading_diff_deg < 3° → rudder = 0.
   - Maintain RPM at 50% during return.

5. ECO-MODE:
   - Prefer rudder changes over RPM changes.
   - Keep RPM at 50% unless CPA < 1000m or emergency.
   - Min RPM: 30%, never 0%.

6. NO MANEUVER:
   - If HOLD_COURSE and not returning → rudder=0, rpm=50.

Respond with valid JSON only. No markdown, no explanation outside JSON."""

        self.last_status = None
        self.last_error = None

    def test_connection(self):
        """Проверка подключения к провайдеру."""
        try:
            if self.provider == 'ollama':
                r = requests.get('http://localhost:11434/api/tags', timeout=5)
                if r.status_code == 200:
                    models = r.json().get('models', [])
                    model_names = [m.get('name', '') for m in models]
                    if any(self.model in m for m in model_names):
                        return True, f"Ollama is running, model {self.model} is available"
                    else:
                        return False, f"Model {self.model} not found. Available: {', '.join(model_names[:5])}"
                else:
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
                else:
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
                else:
                    return False, f"Error {r.status_code}: {r.text[:100]}"

        except requests.exceptions.ConnectionError:
            return False, f"No connection to {self.provider}. Check internet/service."
        except Exception as e:
            return False, f"Error: {str(e)[:100]}"

    def format_analysis_table(self, ships, collision_data):
        """Форматирование данных для LLM в JSON."""
        return json.dumps(collision_data, indent=2, ensure_ascii=False)

    def _call_openai_compatible(self, user_message):
        """Вызов OpenAI-совместимого API"""
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
        """Вызов Anthropic API"""
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
        """Вызов Ollama API"""
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
        Получить скоординированные команды от LLM.
        
        ИСПРАВЛЕНО: правильная обработка ошибок без вторичных исключений.
        """
        content = None  # Инициализируем ПЕРЕД try блоком
        
        if not collision_data:
            return {
                "vessel_commands": {
                    ship.name: {
                        "rudder_deg": 0,
                        "rpm_percent": 50,
                        "reasoning": "No threats"
                    }
                    for ship in ships
                }
            }

        table_text = self.format_analysis_table(ships, collision_data)
        user_message = (
            f"Coordinate maneuvers for all vessels based on this analysis:\n\n"
            f"{table_text}\n\n"
            f"Generate commands for ALL vessels listed above. "
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

            # Удалить возможные markdown-блоки
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
            
            # БЕЗОПАСНЫЙ вывод содержимого (content может быть None)
            if content:
                print(f"Raw content (first 300 chars): {content[:300]}")
            else:
                print("Raw content: None (request failed before response)")

            # Fallback: безопасные команды
            return {
                "vessel_commands": {
                    ship.name: {
                        "rudder_deg": 0,
                        "rpm_percent": 50,
                        "reasoning": f"LLM Error: {error_msg[:50]}"
                    }
                    for ship in ships
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
            if ship.name not in vessel_commands:
                if getattr(ship, 'llm_controlled', False):
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
                    print(f"[LLM→AP] {ship.name}: RESUME ROUTE — {reasoning[:60]}")
                    continue

                if 'course_deg' in cmd and cmd['course_deg'] is not None:
                    course = cmd['course_deg']
                    if course < 0:
                        autopilot.resume_route()
                        print(f"[LLM→AP] {ship.name}: RESUME (via negative course)")
                    else:
                        course = course % 360
                        autopilot.set_hold_course(course)
                        ship.llm_decision = cmd
                        ship.llm_reasoning = reasoning
                        print(f"[LLM→AP] {ship.name}: HOLD COURSE {course:.1f}° — {reasoning[:60]}")
                    continue

                if 'rudder_deg' in cmd:
                    current_heading = ship.get_heading_deg()
                    autopilot.set_hold_course(current_heading)
                    ship.rudder_cmd = np.clip(cmd['rudder_deg'], -35, 35)
                    ship.llm_decision = cmd
                    ship.llm_reasoning = reasoning
                    print(f"[LLM→AP] {ship.name}: direct rudder {cmd['rudder_deg']}° (fallback)")
                    continue

                autopilot.resume_route()
                print(f"[LLM→AP] {ship.name}: unrecognized command, resuming route")
                continue

            rudder = cmd.get("rudder_deg", 0)
            rpm = cmd.get("rpm_percent", 50)

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
                print(f"[LLM] {ship.name}: course {new_course:.1f}° (manual)")
