"""pytest setup: every test starts from the original world and no conferences."""
import pytest

from backend.conference_service import conference_service
from backend.simulation import simulation


@pytest.fixture(autouse=True)
def _reset_world():
    simulation.reset()
    conference_service.clear()
    yield
    simulation.reset()
    conference_service.clear()