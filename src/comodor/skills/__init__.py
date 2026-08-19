"""Authored skills: procedures the user writes once and Comodor follows.

Distinct from the *learned* procedures in :mod:`comodor.learning`, which the
agent distils from its own episodes. These are written by hand, live in files,
and can be committed alongside the code they describe.
"""

from .loader import Skill, SkillError, load, parse
from .registry import SkillRegistry, load_for

__all__ = ["Skill", "SkillError", "SkillRegistry", "load", "load_for", "parse"]
