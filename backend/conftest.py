"""pytest setup: every test starts from the original world."""
import pytest

from simulation import simulation


@pytest.fixture(autouse=True)
def _reset_world():
    simulation.reset()
    yield
    simulation.reset()