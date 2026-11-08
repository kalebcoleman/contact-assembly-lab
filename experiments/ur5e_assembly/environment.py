"""Read assembly settings from the environment, accepting legacy names."""

from os import environ


def setting(name: str, default: str) -> str:
    """Return ASSEMBLY_<name>, else the legacy DOG_<name>, else `default`.

    Args:
        name: Setting name without its prefix, e.g. "BREAKAGE".
        default: Value when neither variable is set.

    Returns:
        The setting's value as text.
    """
    for prefix in ("ASSEMBLY_", "DOG_"):
        if prefix + name in environ:
            return environ[prefix + name]
    return default


def is_set(name: str) -> bool:
    """Tell whether ASSEMBLY_<name> or the legacy DOG_<name> is set.

    Args:
        name: Setting name without its prefix.

    Returns:
        True if either variable is in the environment.
    """
    return f"ASSEMBLY_{name}" in environ or f"DOG_{name}" in environ
