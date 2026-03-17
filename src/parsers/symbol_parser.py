"""Parser for user-defined symbol feature files."""

from __future__ import annotations

from pathlib import Path

from src.models import UserSymbol
from src.parsers.feature_parser import parse_features


def parse_user_symbol(name: str, path: Path) -> UserSymbol:
    """Parse a user-defined symbol's features file.

    Uses the same feature parser as layer features since the format is identical.
    """
    layer_features = parse_features(path)

    return UserSymbol(
        name=name,
        units=layer_features.units,
        symbols=layer_features.symbols,
        features=layer_features.features,
    )


def parse_all_symbols(symbol_paths: dict[str, Path]) -> dict[str, UserSymbol]:
    """Parse all user-defined symbols.

    Args:
        symbol_paths: dict mapping symbol name -> features file path

    Returns:
        dict mapping symbol name -> UserSymbol
    """
    symbols = {}
    for name, path in symbol_paths.items():
        try:
            symbols[name] = parse_user_symbol(name, path)
        except Exception as e:
            print(f"Warning: Failed to parse symbol '{name}': {e}")
    return symbols
