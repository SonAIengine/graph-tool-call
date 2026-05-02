# Contributing to graph-tool-call

Contributions are welcome! Here's how to get started.

## Development Setup

```bash
git clone https://github.com/SonAIengine/graph-tool-call.git
cd graph-tool-call
pip install poetry pre-commit
poetry install --with dev --all-extras
pre-commit install   # auto-runs ruff on every commit
```

The `pre-commit install` step wires up `.pre-commit-config.yaml` so that
`ruff check --fix` and `ruff format` run automatically before each commit.
This catches the same lint issues CI checks, before they reach the remote.

To run the hooks manually on the whole tree:

```bash
pre-commit run --all-files
```

## Running Tests

```bash
poetry run pytest -v
```

## Linting

```bash
poetry run ruff check .
poetry run ruff format --check .
```

## Submitting Changes

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes
4. Run tests and linting
5. Commit with a descriptive message
6. Push and open a Pull Request

## Reporting Issues

Use [GitHub Issues](https://github.com/SonAIengine/graph-tool-call/issues) for bug reports and feature requests.

## Code Style

- Python 3.10+ compatible
- Follow existing patterns in the codebase
- Run `ruff check` and `ruff format` before committing

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
