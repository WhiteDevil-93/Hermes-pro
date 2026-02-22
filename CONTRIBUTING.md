# Contributing to Hermes

Thanks for your interest in contributing! This document covers the process for
contributing to Hermes.

## Getting Started

### Prerequisites

- Python 3.11+
- Docker (for container builds)
- Node.js (for the web frontend)

### Development Setup

```bash
# Clone the repo
git clone https://github.com/WhiteDevil-93/Hermes-pro.git
cd Hermes-pro

# Install in editable mode with dev dependencies
pip install -e '.[dev]'

# Install Playwright browser
playwright install chromium

# Run tests
pytest

# Run linting
ruff check .
ruff format --check .
```

Or use the **Dev Container** (recommended): open the repo in VS Code and select
"Reopen in Container".

## Development Workflow

1. **Fork** the repository
2. **Create a branch** from `main`:
   ```bash
   git checkout -b feature/my-change
   ```
3. **Make your changes** — keep commits focused and atomic
4. **Run checks locally**:
   ```bash
   make lint      # ruff check + format
   make test      # pytest with coverage
   make typecheck # mypy
   ```
5. **Push** your branch and open a **Pull Request**

## Pull Request Guidelines

- Fill out the PR template completely
- Link related issues using `Closes #123`
- Keep PRs focused — one feature or fix per PR
- Add tests for new functionality
- Ensure CI passes before requesting review
- Rebase on `main` if your branch is behind

## Code Standards

| Area        | Tool   | Config              |
|-------------|--------|---------------------|
| Formatting  | Ruff   | `pyproject.toml`    |
| Linting     | Ruff   | `pyproject.toml`    |
| Type checks | mypy   | `pyproject.toml`    |
| Tests       | pytest | `pyproject.toml`    |

- **Line length**: 100 characters
- **Target Python**: 3.11+
- **Async-first**: use `async`/`await` for I/O-bound operations
- **Type annotations**: required for public functions

## Reporting Bugs

Use the [bug report template](https://github.com/WhiteDevil-93/Hermes-pro/issues/new?template=bug_report.yml)
and include:

- Steps to reproduce
- Expected vs actual behavior
- Python version and OS
- Relevant logs

## Security Issues

**Do not open public issues for security vulnerabilities.** See
[SECURITY.md](SECURITY.md) for responsible disclosure instructions.

## License

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE).
