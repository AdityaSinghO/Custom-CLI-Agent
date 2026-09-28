import argparse
import json
import os
import re
import subprocess
import sys

from openai import OpenAI

# 1. Gracefully try importing yaml at top-level
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

API_KEY = os.getenv("OPENROUTER_API_KEY")
BASE_URL = os.getenv("OPENROUTER_BASE_URL", default="https://openrouter.ai/api/v1")


def parse_frontmatter(raw_text: str) -> dict:
    if HAS_YAML:
        return yaml.safe_load(raw_text) or {}

    # Fallback if PyYAML is not installed in the test environment
    metadata = {}
    for line in raw_text.splitlines():
        line = line.strip()
        if line and ":" in line:
            key, val = line.split(":", 1)
            metadata[key.strip()] = val.strip()
    return metadata


def load_skills():
    """Scan .claude/skills/ for SKILL.md files and return a formatted string of available skills."""
    skills_dir = os.path.join(".claude", "skills")
    if not os.path.exists(skills_dir):
        return ""

    skills = []

    for item in sorted(os.listdir(skills_dir)):
        skill_folder = os.path.join(skills_dir, item)
        skill_file = os.path.join(skill_folder, "SKILL.md")

        if os.path.isdir(skill_folder) and os.path.isfile(skill_file):
            try:
                with open(skill_file, "r", encoding="utf-8") as f:
                    content = f.read()

                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        frontmatter_raw = parts[1]
                        
                        metadata = parse_frontmatter(frontmatter_raw)
                        
                        name = metadata.get("name", item)
                        description = str(metadata.get("description", "")).strip()

                        skills.append(f"- {name}: {description}")
            except Exception as e:
                print(f"Error reading skill in {skill_folder}: {e}", file=sys.stderr)

    if not skills:
        return ""

    return (
        "You have access to the following skills:\n\n"
        + "\n".join(skills)
        + "\n\nIf a skill matches the user's request, call the Skill tool with its name\n"
        + "and follow the instructions it returns."
    )


def get_expanded_skill_body(skill_name: str, raw_args: str) -> tuple[str, bool]:
    """Helper to load a skill, substitute arguments, and determine if it's a subagent fork.
       Returns: (body_string, is_fork)
    """
    skill_file = os.path.join(".claude", "skills", skill_name, "SKILL.md")
    
    if not os.path.isfile(skill_file):
        return f"Error: Skill '{skill_name}' not found.", False

    try:
        with open(skill_file, "r", encoding="utf-8") as f:
            content = f.read()

        if content.startswith("---"):
            file_parts = content.split("---", 2)
            if len(file_parts) >= 3:
                frontmatter_raw = file_parts[1]
                metadata = parse_frontmatter(frontmatter_raw)
                is_fork = metadata.get("context", "").strip().lower() == "fork"
                
                body = file_parts[2].strip()
                arg_list = raw_args.split()

                # Substitute $ARGUMENTS[n]
                body = re.sub(
                    r'\$ARGUMENTS\[(\d+)\]',
                    lambda m: arg_list[int(m.group(1))] if int(m.group(1)) < len(arg_list) else "",
                    body
                )

                # Substitute $ARGUMENTS
                body = body.replace("$ARGUMENTS", raw_args)

                # Substitute $n shorthand
                body = re.sub(
                    r'\$(\d+)',
                    lambda m: arg_list[int(m.group(1))] if int(m.group(1)) < len(arg_list) else "",
                    body
                )

                # Only prepend Skill Location Header if NOT a fork (subagents get pure instructions)
                if not is_fork:
                    header = (
                        f"Skill: {skill_name} (located at .claude/skills/{skill_name})\n"
                        f"Paths in the instructions below are relative to that folder.\n\n"
                    )
                    body = header + body
                
                return body, is_fork
                
        return f"Error: Invalid skill format for '{skill_name}'.", False
    except Exception as e:
        return f"Error reading skill body for {skill_name}: {e}", False


def run_agent_loop(client, messages):
    """Executes the agent loop until the LLM returns a final text response."""
    tools = [
        {
            "type": "function",
            "function": {
                "name": "Skill",
                "description": "Load a skill's instructions into the conversation",
                "parameters": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "The name of the skill to use"
                        },
                        "args": {
                            "type": "string",
                            "description": "Optional arguments for the skill"
                        }
                    }
                }
            }
        },
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
            "function": {
                "name": "Write",
                "description": "Write content to a file",
                "parameters": {
                    "type": "object",
                    "required": ["file_path", "content"],
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "The path of the file to write to"
                        },
                        "content": {
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
                            "description": "The command to execute",
                        }
                    }
                }
            }
        }
    ]

    while True:
        chat = client.chat.completions.create(
            model="anthropic/claude-haiku-4.5",
            messages=messages,
            tools=tools,
        )

        if not chat.choices:
            raise RuntimeError("no choices in response")

        response_message = chat.choices[0].message
        messages.append(response_message)

        if not response_message.tool_calls:
            return response_message.content

        for tool_call in response_message.tool_calls:
            tool_args = json.loads(tool_call.function.arguments)  # type: ignore

            if tool_call.function.name == "Skill":  # type: ignore
                skill_name = tool_args.get("name", "")
                skill_args = tool_args.get("args", "")

                body, is_fork = get_expanded_skill_body(skill_name, skill_args)

                if body.startswith("Error"):
                    skill_content = body
                elif is_fork:
                    # Spawn Subagent
                    sub_messages = [{"role": "user", "content": body}]
                    sub_result = run_agent_loop(client, sub_messages)
                    skill_content = f"Skill {skill_name} ran in a separate context and returned: {sub_result}"
                else:
                    # Process inline
                    skill_content = body

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": skill_content
                    }
                )

            elif tool_call.function.name == "Read":  # type: ignore
                file_path = tool_args.get("file_path", "")
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

            elif tool_call.function.name == "Write":  # type: ignore
                file_path = tool_args.get("file_path", "")
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
                        shell=True,
                        capture_output=True,
                        text=True,
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


def main():
    p = argparse.ArgumentParser()
    p.add_argument("-p", required=True)
    args = p.parse_args()

    if not API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not set")

    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

    messages = []

    # 1. Load and inject Level 1 skills
    skills_prompt = load_skills()
    if skills_prompt:
        messages.append({"role": "system", "content": skills_prompt})

    # 2. Process User Prompt for Stacking Multiple Skills & Argument Substitution
    user_prompt = args.p
    tokens = user_prompt.split()
    
    skills_dir = os.path.join(".claude", "skills")
    invoked_skills = []
    arg_tokens = []

    # Parse tokens to find stacked skills
    for i, token in enumerate(tokens):
        if token.startswith("/"):
            skill_name = token[1:]
            skill_file = os.path.join(skills_dir, skill_name, "SKILL.md")
            
            if os.path.isfile(skill_file):
                invoked_skills.append(skill_name)
                
                # Check if it's a fork to determine stacking stop condition
                is_fork = False
                try:
                    with open(skill_file, "r", encoding="utf-8") as f:
                        content = f.read()
                    if content.startswith("---"):
                        parts = content.split("---", 2)
                        if len(parts) >= 3:
                            meta = parse_frontmatter(parts[1])
                            is_fork = meta.get("context", "").strip().lower() == "fork"
                except Exception:
                    pass
                
                if is_fork:
                    arg_tokens = tokens[i+1:]
                    break
            else:
                arg_tokens = tokens[i:]
                break
        else:
            arg_tokens = tokens[i:]
            break

    # 3. Inject skills or raw prompt into the messages array
    if invoked_skills:
        raw_args = " ".join(arg_tokens)
        for skill_name in invoked_skills:
            body, is_fork = get_expanded_skill_body(skill_name, raw_args)
            if is_fork:
                # Fork invoked manually via Slash command
                sub_messages = [{"role": "user", "content": body}]
                sub_result = run_agent_loop(client, sub_messages)
                messages.append({"role": "user", "content": f"Skill {skill_name} ran in a separate context and returned: {sub_result}"})
            else:
                messages.append({"role": "user", "content": body})
    else:
        # If no skills were matched at the start, just use the raw prompt
        messages.append({"role": "user", "content": user_prompt})

    # 4. Kick off the main agent loop
    final_output = run_agent_loop(client, messages)
    if final_output:
        print(final_output)


if __name__ == "__main__":
    main()