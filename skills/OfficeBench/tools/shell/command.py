import os
import sys
import fire
import subprocess

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from _log import log_tool_call

TESTBED_DIR = os.environ.get("OFFICEBENCH_TESTBED", "/workspace/testbed")


@log_tool_call("shell.command")
def main(command):
    if isinstance(command, list):
        command = " ".join(command)
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, cwd=TESTBED_DIR
        )
        output = result.stdout + result.stderr
        return f"OBSERVATION: Successfully executed command: {command}. The output was [{output}]."
    except Exception as e:
        return f"OBSERVATION: Failed to execute command: {command}. Error: {e}"


if __name__ == "__main__":
    fire.Fire(main)
