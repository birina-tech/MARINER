import os

### Get key from environment
key = os.getenv("DASHSCOPE_API_KEY", "sk-ws-H.IERDXH.9zug.MEUCIQCxEF7Dcg_N2VmXPlcyErqIQvlaiIikL8QlWEpVFI_AgwIge7FYWk312PHsiWZa9UpgF90dK6ab97fs-DzCCH30DOQ")

print("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
print(f"Key loaded: {key[:8]}...{key[-4:] if key else ''}")
print(f"Total Key Length: {len(key)} characters")

### Check for accidental spaces or newlines
if "\n" in key or "\r" in key or " " in key:
    print("WARNING: Key contains hidden whitespace or line breaks!")
else:
    print("Key structure looks clean.")
print("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")