"""constants.py - 集中管理运行参数与固定文本"""

# config.py
CONFIG_DEFAULT_MAX_STEPS = 100000
CONFIG_DEFAULT_MAX_TOKENS = 65536
CONFIG_DEFAULT_REQUEST_TIMEOUT = 600
CONFIG_DEFAULT_MAX_RETRIES = 3
CONFIG_MAX_RETRIES = 10

# agent.py
AGENT_DEFAULT_MAX_STEPS = 100000

# model.py
MODEL_DEFAULT_MAX_TOKENS = 65536

# terminal.py
TERMINAL_REFRESH_PER_SECOND = 10
TERMINAL_INTRO = "Enter a task; /history shows messages, /exit quits. Ctrl+C interrupts a turn."
TERMINAL_PROMPT = "\n[bold cyan]xsh> [/]"
TERMINAL_REQUIRED_ERROR = "an interactive terminal is required; redirecting or piping output is not supported"

# cli.py
CLI_ENV_FILE = ".env"
CLI_SESSION_DIRECTORY = ".xsh/sessions"
CLI_SESSION_TIMESTAMP_FORMAT = "%Y%m%d-%H%M%S-"
CLI_SESSION_ID_LENGTH = 8
CLI_SESSION_SUFFIX = ".jsonl"
CLI_EXIT_COMMANDS = {"/exit", "/quit"}
CLI_HISTORY_COMMANDS = {"/history"}
CLI_INTERRUPT_EXIT_CODE = 130

# prompt.py
PROMPT_RESOURCE_PATH = "prompts/system.md"
PROMPT_INSTRUCTIONS_FILE = "AGENTS.md"
PROMPT_SHELL_INSTRUCTIONS = (
    "\nYour shell tool runs foreground commands with the workspace as its working directory. "
    "It is not sandboxed and has no persistent terminal or background job support. "
    "Use the shell dialect advertised in its tool description. Use it for tests and build commands.\n\n"
    "Check the [exit code: N] marker on every shell result; investigate failures and "
    "timeouts before moving on. After a timeout, inspect state before retrying commands "
    "with side effects.\n"
)
PROMPT_MAX_INSTRUCTIONS_BYTES = 128000

# session.py
SESSION_FORMAT_VERSION = 1

# tools/base.py
BASE_OUTPUT_LIMIT = 64000
BASE_TRUNCATION_MARKER = "\n[Output truncated; request a smaller range or narrower search.]"

# tools/files.py
FILES_MAX_FILE_BYTES = 10 * 1024 * 1024
FILES_SKIP_DIRS = frozenset({".git", ".xsh", ".venv", ".conda", "node_modules", "__pycache__"})
FILES_DEFAULT_READ_LIMIT = 500
FILES_MAX_READ_LIMIT = 2000
FILES_DEFAULT_GLOB = "*"
FILES_RESERVED_DIRECTORY = ".xsh"
FILES_SCAN_LIMIT = 100000
FILES_RESULT_LIMIT = 1000

# tools/shell.py
SHELL_DEFAULT_TIMEOUT_SECONDS = 120
SHELL_MAX_TIMEOUT_SECONDS = 600
SHELL_MAX_OUTPUT_BYTES = 256000
SHELL_TRUNCATION_MARKER = "\n[Output truncated; rerun with a narrower command or redirect to a file.]"
SHELL_TIMEOUT_MARKER = " [timed out; inspect state before retrying commands with side effects]"
