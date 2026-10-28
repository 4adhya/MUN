"""pytest setup: every test starts from the original world, no conferences, and no persistence.

Persistence is ON by default in a real run (SQLite, ./mun.db). Tests must stay in-memory and
isolated, so this autouse fixture also detaches any persistence collaborator from the shared
conference service, both before and after each test. Tests that specifically exercise persistence
attach their own in-memory/temp-file repository locally (see test_persistence.py).
"""
import pytest

from backend.conference_service import conference_service
from backend.persistence.service import NullPersistenceService
from backend.simulation import simulation


@pytest.fixture(autouse=True)
def _reset_world():
    conference_service.set_persistence(NullPersistenceService())
    simulation.reset()
    conference_service.clear()
    yield
    conference_service.set_persistence(NullPersistenceService())
    simulation.reset()
    conference_service.clear()