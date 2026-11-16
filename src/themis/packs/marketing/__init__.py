"""The marketing content pack: what evidence means in content work. See docs/packs/marketing.md."""

from themis.packs import load_modules
from themis.packs.marketing.pack import pack

load_modules(__name__, list(__path__))

__all__ = ["pack"]
