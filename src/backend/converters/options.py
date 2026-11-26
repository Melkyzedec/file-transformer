"""Validation des options de conversion reçues de l'interface."""

DEFAULT_QUALITY = 90
MIN_QUALITY = 1
MAX_QUALITY = 100


def parse_quality(options) -> int:
    """Qualité JPG/WebP/JXL : entier de 1 à 100 (90 si absente)."""
    value = (options or {}).get('quality')
    if value is None:
        return DEFAULT_QUALITY
    if isinstance(value, bool) or not isinstance(value, int) or not MIN_QUALITY <= value <= MAX_QUALITY:
        raise ValueError(
            f"La qualité doit être un entier compris entre {MIN_QUALITY} et {MAX_QUALITY}."
        )
    return value


def parse_keep_aspect_ratio(options) -> bool:
    """Conservation des proportions : booléen (vrai si absente)."""
    value = (options or {}).get('keep_aspect_ratio')
    if value is None:
        return True
    if not isinstance(value, bool):
        raise ValueError("L'option « conserver les proportions » doit valoir vrai ou faux.")
    return value
