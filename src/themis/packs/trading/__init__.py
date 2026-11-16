"""The trading pack: what evidence means in trading research. See docs/packs/trading.md."""

from themis.packs import load_modules
from themis.packs.trading.pack import pack

load_modules(__name__, list(__path__))

__all__ = ["pack"]
