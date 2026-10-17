"""Command-line entry point."""


def greet(name: str = "world") -> str:
    """Return the greeting printed by the CLI."""
    return f"Hello, {name}!"


def main() -> None:
    """Print the greeting."""
    print(greet())
