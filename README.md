# Custom CLI Agent

A minimal, from-scratch **agentic coding assistant for the command line**. Give it a prompt, and it runs an LLM-driven loop that can read files, write files, and execute shell commands to complete your task, all in a single Python file.

Built on the OpenAI-compatible SDK and [OpenRouter](https://openrouter.ai), so you can swap in any tool-calling model with a one-line change.

---

## Features

- **Agent loop**: the model keeps calling tools and observing results until it decides the task is done.
- **Three built-in tools**:
  | Tool    | Description                                              |
  |---------|----------------------------------------------------------|
  | `Read`  | Read and return the contents of a file                   |
  | `Write` | Write content to a file (creates parent directories)     |
  | `Bash`  | Execute a shell command and return stdout + stderr       |
- **Model-agnostic**: works with any OpenRouter model that supports tool calling (defaults to `anthropic/claude-haiku-4.5`).
- **Tiny footprint**: one file, one dependency.

## How It Works

```
┌──────────┐   prompt    ┌─────────┐   tool calls   ┌──────────────────┐
│   User   │ ──────────▶ │   LLM   │ ─────────────▶ │ Read/Write/Bash  │
└──────────┘             └─────────┘ ◀───────────── └──────────────────┘
                              │         tool results
                              ▼
                        final answer (printed)
```

1. Your prompt is sent to the model along with the tool definitions.
2. If the response contains tool calls, each is executed locally and the result is appended to the conversation.
3. The updated conversation is sent back to the model.
4. This repeats until the model responds without any tool calls, at which point the final message is printed.

## Requirements

- Python 3.9+
- An [OpenRouter API key](https://openrouter.ai/keys)
- The `openai` Python package

## Installation

```bash
git clone https://github.com/AdityaSinghO/custom-cli-agent.git
cd custom-cli-agent

python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install openai
```

## Configuration

Set your API key as an environment variable:

```bash
export OPENROUTER_API_KEY="your-api-key-here"
```

Optionally override the API base URL (defaults to OpenRouter):

```bash
export OPENROUTER_BASE_URL="https://openrouter.ai/api/v1"
```

| Variable              | Required | Default                          |
|-----------------------|----------|----------------------------------|
| `OPENROUTER_API_KEY`  | Yes      | none                             |
| `OPENROUTER_BASE_URL` | No       | `https://openrouter.ai/api/v1`   |

## Usage

Pass your task with the `-p` flag:

```bash
python main.py -p "Read main.py and summarize what it does"
```

### Examples

```bash
# Explore and explain a codebase
python main.py -p "List the files in this directory and explain the project structure"

# Generate a file
python main.py -p "Create hello.py that prints 'Hello, world!' and run it"

# Fix a bug
python main.py -p "Run the tests, find why they fail, and fix the code"
```

## Changing the Model

The model is set in the `chat.completions.create` call in `main.py`:

```python
chat = client.chat.completions.create(
    model="anthropic/claude-haiku-4.5",
    messages=messages,
    tools=tools,
)
```

Replace it with any tool-calling model available on OpenRouter.

## Extending the Agent

Adding a new tool takes two steps:

1. Add a tool schema to the `tools` list (name, description, JSON-schema parameters).
2. Add a matching `elif tool_call.function.name == "YourTool":` branch in the tool-execution loop that appends a `role: "tool"` message with the result.

## ⚠️ Security Notice

This agent executes model-generated shell commands directly on your machine with `shell=True` and can read or overwrite any file your user can access. There is no sandboxing or confirmation step.

- Run it in a container, VM, or throwaway directory when experimenting.
- Never point it at directories containing secrets or data you can't afford to lose.
- Review the prompts you give it, especially when they include untrusted content.

## Roadmap

- [ ] Confirmation prompts before running `Bash` or `Write`
- [ ] Sandboxed command execution
- [ ] Command timeouts and output truncation
- [ ] Streaming responses
- [ ] Interactive multi-turn mode
- [ ] Additional tools (search, edit, list directory)

## Contributing

Issues and pull requests are welcome. Fork the repo, create a feature branch, and open a PR describing your change.

## License

Distributed under the MIT License. See `LICENSE` for details.

## Author

**Aditya** · [@AdityaSinghO](https://github.com/AdityaSinghO)
