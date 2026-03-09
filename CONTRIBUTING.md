# Contributing to DockPulse

Thank you for your interest in contributing to DockPulse. This guide will help you
get started.

## Development Setup

1. **Fork and clone the repository:**

   ```bash
   git clone https://github.com/<your-username>/dockpulse.git
   cd dockpulse
   ```

2. **Create a virtual environment and install dependencies:**

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -e ".[dev]"
   ```

3. **Verify your setup:**

   ```bash
   pytest
   ruff check src/ tests/
   ```

## Development Workflow

1. **Create a feature branch** from `main`:

   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes.** Follow the existing code style and conventions.

3. **Write tests** for any new functionality. Place tests in the `tests/` directory
   and follow the existing naming convention (`test_<module>.py`).

4. **Run the full test suite:**

   ```bash
   pytest --cov=dockpulse
   ```

5. **Lint and format your code:**

   ```bash
   ruff check src/ tests/ --fix
   ruff format src/ tests/
   ```

6. **Type-check:**

   ```bash
   mypy src/dockpulse/
   ```

7. **Commit your changes** with a clear, descriptive commit message:

   ```bash
   git commit -m "Add support for per-service headroom configuration"
   ```

8. **Push and open a Pull Request** against `main`.

## Code Guidelines

- Target Python 3.10+ and use modern syntax (type hints, `match` statements where
  appropriate, `|` union types).
- Keep functions focused and small. Prefer composition over inheritance.
- Use dataclasses for data structures (no Pydantic dependency).
- All public functions and classes must have docstrings.
- Avoid adding new dependencies unless absolutely necessary. Discuss in an issue first.

## Reporting Issues

- Use the provided issue templates for bug reports and feature requests.
- Include reproduction steps, expected behavior, and actual behavior.
- Include your Python version, Docker version, and OS.

## Pull Request Checklist

- [ ] Tests pass (`pytest`)
- [ ] Linter passes (`ruff check`)
- [ ] Type checker passes (`mypy`)
- [ ] New functionality is documented
- [ ] Commit messages are clear and descriptive

## License

By contributing, you agree that your contributions will be licensed under the MIT
License.
