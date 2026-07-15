"""
test_litellm_isolated.py
Isolated testing script to catch raw LiteLLM tracebacks.
"""
import os
import litellm
import traceback

# 1. Match your controller's guardrails exactly
litellm.telemetry = False
litellm.drop_params = True

def run_isolated_test():
    # --- CONFIGURATION (Change this to test different backends) ---
    provider = "ollama"  # Options: 'ollama', 'groq', 'openai', etc.
    model = "ollama/llama3"  # Use the prefix/model format from your app
    
    # Optional: If you are testing a cloud provider, add the key directly here
    # os.environ["GROQ_API_KEY"] = "your-actual-key-here"
    # os.environ["OPENAI_API_KEY"] = "your-actual-key-here"
    
    print(f"=== Testing Provider: {provider} | Model: {model} ===")
    
    kwargs = {
        "model": model,
        "messages": [{"role": "user", "content": "Hi"}]
    }
    
    # Match your app's specific alibaba/vllm override if testing qwen
    if provider == "qwen":
        kwargs["api_base"] = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    try:
        print("Sending request to litellm.completion...")
        response = litellm.completion(**kwargs)
        print("\n✅ SUCCESS!")
        print(f"Response Content: {response.choices[0].message.content}")
        
    except Exception as e:
        print("\n❌ CRASH DETECTED!")
        print(f"Caught Exception Type: {type(e).__name__}")
        print(f"Exception Message: {str(e)}")
        print("\n--- RAW FULL TRACEBACK ---")
        traceback.print_exc()  # This prints the EXACT file and line number where it failed

if __name__ == "__main__":
    run_isolated_test()