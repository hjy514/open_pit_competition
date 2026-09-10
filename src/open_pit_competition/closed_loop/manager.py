# -*- coding: utf-8 -*-
"""Compatibility name for the Closed Loop V1 coordinator."""

from .coordinator import ClosedLoopCoordinator, ClosedLoopConfig

ClosedLoopManager = ClosedLoopCoordinator

__all__ = ["ClosedLoopCoordinator", "ClosedLoopConfig", "ClosedLoopManager"]
