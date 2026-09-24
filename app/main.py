import argparse
from email import message
import os
import sys
import json
import subprocess

from openai import OpenAI

API_KEY = os.getenv("OPENROUTER_API_KEY")
BASE_URL = os.getenv("OPENROUTER_BASE_URL", default="https://openrouter.ai/api/v1")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("-p", required=True)
    args = p.parse_args()

    if not API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not set")

    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

    messages = [{"role": "user", "content": args.p}]

    tools=[
            {
            "type": "function",
            "function": {
                "name": "Read",
                "description": "Read and return the contents of a file",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "The path to the file to read",
                            }
                        },
                    "required": ["file_path"],
                    },
                },
            },
            {
                "type": "function",
                "function":{
                    "name": "Write",
                    "description": "Write content to a file",
                    "parameters":{
                        "type": "object",
                        "required": ["file_path", "content"],
                        "properties":{
                            "file_path":{
                                "type":"string",
                                "description": "The path of the file to write to"
                            },
                            "content":{
                                "type": "string",
                                "description": "The content to write into the file"
                            }
                        }
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "Bash",
                    "description": "Execute a shell command",
                    "parameters": {
                        "type": "object",
                        "required": ["command"],
                        "properties": {
                            "command": {
                                "type": "string",
                                "description":"The command to execute",
                            }
                        }
                    }
                }
            }
        ]
    while True:
        chat = client.chat.completions.create(
            model = "anthropic/claude-haiku-4.5",
            messages = messages,
            tools = tools,
        )

        if not chat.choices:
            raise RuntimeError("no choices in response")

        response_message = chat.choices[0].message
        messages.append(response_message)

        if not response_message.tool_calls:
            if response_message.content:
                print(response_message.content)
            break

        for tool_call in response_message.tool_calls:
            tool_args = json.loads(tool_call.function.arguments) # type: ignore
            file_path = tool_args.get("file_path", "")

            if tool_call.function.name == "Read": # type: ignore
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        file_content = f.read()
                except Exception as e:
                    file_content = f"Error reading file: {e}"

                messages.append(
                    {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": file_content
                    }
                )

            elif tool_call.function.name == "Write": # type: ignore
                content = tool_args.get("content", "")

                try:
                    dir_name = os.path.dirname(file_path)
                    if dir_name:
                        os.makedirs(dir_name, exist_ok=True)

                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(content)

                    result_content = f"Success: Content written to {file_path}"

                except Exception as e:
                    result_content = f"Error writing to file: {e}"

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result_content
                    }
                )

            elif tool_call.function.name == "Bash":  # type: ignore
                command = tool_args.get("command", "")

                try:
                    res = subprocess.run(
                        command,
                        shell = True,
                        capture_output = True,
                        text = True,
                    )
                    output = res.stdout + res.stderr
                except Exception as e:
                    output = f"Error executing bash command: {e}"

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": output
                    }
                )

    # You can use print statements as follows for debugging, they'll be visible when running tests.
    print("Logs from your program will appear here!", file=sys.stderr)


if __name__ == "__main__":
    main()
