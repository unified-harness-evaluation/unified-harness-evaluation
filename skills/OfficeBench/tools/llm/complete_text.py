import os
import sys
import fire
import litellm

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from _log import log_tool_call


@log_tool_call("llm.complete_text")
def main(prompt):
    try:
        model = os.environ.get("AGENT_MODEL", "azure/gpt-4.1")
        response = litellm.completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=512,
        )
        return response.choices[0].message.content or ""
    except Exception as e:
        return f"Error: {e}"


if __name__ == "__main__":
    fire.Fire(main)
