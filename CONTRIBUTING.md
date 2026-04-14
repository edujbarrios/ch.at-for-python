# Contributing to ch.at for Python

Thanks for your interest. This is an unofficial Python port maintained by Eduardo J. Barrios. Contributions that improve correctness, fix bugs, or extend functionality are welcome.

## Ground rules

- This port mirrors the design of the [original ch.at](https://github.com/Deep-ai-inc/ch.at). Don't add features that would diverge from the original's philosophy (no accounts, no logs, no tracking).
- Keep changes focused. One concern per PR.
- All code must work on Python 3.10+.

## Getting started

```bash
git clone https://github.com/edujbarrios/ch.at-for-python.git
cd ch.at-for-python

pip install -e ".[dev]"

cp llm.py.example llm.py
# Add your API key to llm.py
```

## Running the tests

```bash
# Start the server in one terminal
python chat.py

# Run the test suite in another
python selftest/main.py http://localhost:8080

# Or with pytest
pytest selftest/ -v
```

## Reporting bugs

Open a GitHub issue with:
- Python version (`python --version`)
- OS and architecture
- Steps to reproduce
- Expected vs actual behaviour

## Submitting changes

1. Fork the repository and create a branch: `git checkout -b fix/short-description`
2. Make your changes
3. Run the selftest and confirm it passes
4. Commit with a clear message following the format already used: `fix: ...`, `feat: ...`, `docs: ...`, `chore: ...`
5. Open a pull request against `master`

## Commit style

```
fix: short description of what was broken
feat: short description of what was added
docs: short description of what was documented
chore: dependency updates, formatting, tooling
```

## What not to do

- Don't add authentication or user tracking — this breaks the project's core design
- Don't add runtime config files (`.env`, YAML, etc.) — configuration lives in `chat.py` by design
- Don't add a web framework other than Flask without a compelling reason
- Don't add logging of user queries

## Author

Eduardo J. Barrios — [edujbarrios@outlook.com](mailto:edujbarrios@outlook.com)
