# Secure_Code_Review
  
> AI-powered source code analysis that runs 100% locally. Zero cloud calls, zero data leaks, zero API keys.

Uses [Ollama](https://ollama.com) and any local LLM to scan source code for security vulnerabilities, bugs, performance bottlenecks, and code quality issues — all on your machine.

```bash
code-reviewer myfile.py
```

## Features

- **100% local** — all inference runs on your machine via Ollama. Zero data sent to third parties.
- **50+ languages** — Python, JavaScript, TypeScript, Go, Rust, Java, C, C++, C#, PHP, Ruby, Kotlin, Swift, Shell, SQL, Terraform, and more.
- **Severity-scored issues** — each finding classified as Critical, High, Medium, Low, or Info with a numerical score (0–100).
- **POC with line numbers** — every issue includes the exact line number and a code snippet showing the vulnerable code in context with a `>>>` marker.
- **Multi-format output** — terminal, Markdown, HTML, or JSON reports.
- **Directory scanning** — recursively review entire projects with parallel file processing.
- **Auto model selection** — picks the best model for your available RAM. Falls back gracefully on constrained systems.
- **Large file support** — automatically chunks files >300 lines for thorough analysis.
- **Language-specific focus** — tailored vulnerability hints per language (e.g., buffer overflows in C, XSS in JS, SQL injection in PHP).

## Requirements

| Dependency | Minimum |
|---|---|
| Python | 3.8+ |
| [Ollama](https://ollama.com) | 0.24.0+ |
| Python `requests` | any recent version |
| RAM | 2 GB (3B model) / 8 GB (8B model) |

## Installation

### 1. Install Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl start ollama
```

### 2. Pull a model

```bash
# Recommended for most systems:
ollama pull llama3.2:3b

# For deeper analysis (needs ~8 GB RAM):
ollama pull qwen3:8b
```

### 3. Download the reviewer

```bash
curl -LO https://raw.githubusercontent.com/<your-org>/code-reviewer/main/code-reviewer.py
chmod +x code-reviewer.py
sudo ln -s "$PWD/code-reviewer.py" /usr/local/bin/code-reviewer
```

Or just save `code-reviewer.py` anywhere and run with `python3 code-reviewer.py`.

### 4. Install Python dependency

```bash
pip install requests
```

## Usage

```bash
# Review a single file
code-reviewer app.py

# Review a directory
code-reviewer src/

# Recursive directory scan
code-reviewer /path/to/project -r

# Multiple files or dirs
code-reviewer main.js lib/ tests/

# Export as Markdown
code-reviewer src/ -r -f markdown -o review.md

# Export as HTML report
code-reviewer . --exclude node_modules -f html -o report.html

# Export as JSON (for CI pipelines)
code-reviewer app.py -f json -o results.json

# Use a specific model
code-reviewer file.py -m qwen3:8b

# Custom Ollama URL (e.g., remote instance)
code-reviewer file.py -u http://192.168.1.100:11434

# Quiet mode (minimal output)
code-reviewer src/ -r -q
```

### Options

| Flag | Description | Default |
|---|---|---|
| `paths` | File(s) or directories to review | (required) |
| `-r, --recursive` | Scan directories recursively | off |
| `-m, --model` | Ollama model name | auto-detected |
| `-u, --url` | Ollama API base URL | `http://localhost:11434` |
| `-f, --format` | Output format | `terminal` |
| `-o, --output` | Write report to file | stdout |
| `-t, --timeout` | Per-request timeout (seconds) | `180` |
| `--exclude` | Extra glob ignore patterns | — |
| `--workers` | Parallel file workers | `2` |
| `-q, --quiet` | Suppress progress output | off |

## Output Formats

### Terminal

```
  ============================================================
  SUMMARY  Model: llama3.2:3b  Files: 1
  Issues: 1  C:1 H:0 M:0 L:0 I:0
  Avg score: 75/100
  ============================================================

  ============================================================
  /home/user/project/auth.py
  Lang: Python  |  Score: 75/100  |  Issues: 1  (C:1 H:0 M:0 L:0 I:0)
  ============================================================
  [CRITICAL] [security] Hashing password using broken SHA-1.:9
                7 |
                8 |
         >>>    9 | def get_password_hash(password):
               10 |     """Hash a password — WARNING: uses broken SHA-1."""
               11 |     return hashlib.sha1(password.encode()).hexdigest()
```

### Markdown

```markdown
# Code Review Report
**Model:** `llama3.2:3b`  |  **Date:** 2026-05-24 10:23
**Files:** 1

## Summary
| Severity | Count |
|---|--:|
| Critical | 1 |
| High | 0 |
| Medium | 0 |
| Low | 0 |
| Info | 0 |

### 🔴 [CRITICAL] security (line 9)
**Hashing password using broken SHA-1.**

Using SHA-1 for password hashing is insecure and susceptible to collision attacks.

> **Suggestion:** Use bcrypt, argon2, or PBKDF2 instead.

```python
    7 |
    8 |
>>> 9 | def get_password_hash(password):
   10 |     """Hash a password — WARNING: uses broken SHA-1."""
   11 |     return hashlib.sha1(password.encode()).hexdigest()
```
```

### HTML

Run with `-f html -o report.html` to generate a styled, self-contained HTML report with severity-colored issues and formatted suggestions.

### JSON

```json
{
  "model": "llama3.2:3b",
  "date": "2026-05-24T10:23:00",
  "files": 1,
  "results": {
    "/path/to/file.py": {
      "score": 85,
      "total": 1,
      "issues": [
        {
          "severity": "critical",
          "type": "security",
          "line": 9,
          "message": "Hashing password using broken SHA-1.",
          "detail": "Using SHA-1 for password hashing is insecure...",
          "suggestion": "Use bcrypt, argon2 or PBKDF2 instead.",
          "code": ">>>   9 | def get_password_hash(password):\n     10 |     \"\"\"Hash a password...\"\"\"\n     11 |     return hashlib.sha1(password.encode()).hexdigest()"
        }
      ]
    }
  }
}
```

## Supported Languages

Python, JavaScript, TypeScript, JSX, TSX, Go, Rust, Java, C, C++, C#, Ruby, PHP, Swift, Kotlin, Shell/Bash, Perl, Lua, SQL, YAML, JSON, XML, HTML, CSS, Vue, Svelte, Terraform, TOML, INI, Dockerfile, Makefile, CMake, OCaml, F#, Haskell, Elixir, Erlang, Groovy, Gradle, Zig, Protocol Buffers, and more.

## How It Works

1. **File discovery** — scans provided paths, filters by supported extensions, skips common build/cache directories.
2. **Language detection** — identifies language from file extension and injects vulnerability-specific hints into the prompt.
3. **Chunking** — files over 300 lines are split into chunks for focused analysis.
4. **AI review** — each chunk is sent to Ollama's chat API with a structured system prompt requesting JSON output. The temperature is set to 0.1 for consistent, deterministic results.
5. **Score calculation** — starts at 100, subtracts: Critical=-25, High=-15, Medium=-8, Low=-3, Info=-1.
6. **POC extraction** — for each issue, the tool reads the original file and extracts a 5-line code snippet with `>>>` pointing at the vulnerable line. Blank lines and imports are skipped to find the actual code.
7. **Report generation** — merges chunk results, deduplicates positives, produces the chosen output format.

## Model Recommendations

| System RAM | Recommended Model | Quality | Speed |
|---|---|---|---|
| < 4 GB | `llama3.2:3b` | Basic | ~8 tok/s |
| 4–8 GB | `llama3:8b` | Good | ~4 tok/s |
| 8+ GB | `qwen3:8b` | Best | ~3.5 tok/s |
| 16+ GB | `qwen3:14b` or `codellama:13b` | Excellent | ~2 tok/s |

The tool auto-selects the best model based on available memory. Override with `-m` to force a specific model.

## CI/CD Integration

```yaml
# GitHub Actions example
- name: AI Code Review
  run: |
    pip install requests
    curl -LO https://raw.githubusercontent.com/.../code-reviewer.py
    chmod +x code-reviewer.py
    ./code-reviewer.py src/ -f json -o review.json
```

## Security

- **No data leaves your machine** — all inference runs locally through Ollama.
- **No telemetry** — the tool makes no external network calls except to your Ollama instance.
- **No API keys** — no OpenAI, Anthropic, or other cloud API dependencies.
- **Safe for proprietary code** — review sensitive codebases without disclosure risk.
