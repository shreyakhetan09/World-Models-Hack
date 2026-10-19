from app.models import Action, Hazard
from app.safety import SafetyLayer


def fire(y=800, x=500, sev=3):
    return Hazard(point=(y, x), label="fire", severity=sev)


def test_blocks_forward_into_deadly_hazard():
    s = SafetyLayer()
    action, why = s.check(Action(move="W", duration_ms=800), [fire()])
    assert action.move == "S" and why and "fire" in why


def test_allows_forward_when_hazard_is_off_to_the_side_or_minor():
    s = SafetyLayer()
    assert s.check(Action(move="W"), [fire(x=100)])[1] is None
    assert s.check(Action(move="W"), [fire(sev=2)])[1] is None
    assert s.check(Action(move="W"), [fire(y=300)])[1] is None


def test_turning_away_is_fine_with_hazard_ahead():
    s = SafetyLayer()
    action, why = s.check(Action(look="left", duration_ms=500), [fire()])
    assert why is None and action.look == "left"


def test_breaks_oscillation():
    s = SafetyLayer()
    results = [s.check(Action(look=side, duration_ms=400), []) for side in ["left", "right"] * 3]
    assert all(why is None for _, why in results[:-1])
    action, why = results[-1]
    assert why and action.move == "W"


def test_oscillation_with_hazard_ahead_turns_instead_of_forward():
    s = SafetyLayer()
    for side in ["left", "right"] * 2 + ["left"]:
        s.check(Action(look=side), [fire(sev=2)])
    action, why = s.check(Action(look="right"), [fire(sev=2)])
    assert why and action.move == "none" and action.look == "right"


def test_forward_move_resets_oscillation_window():
    s = SafetyLayer()
    for side in ["left", "right", "left"]:
        s.check(Action(look=side), [])
    s.check(Action(move="W"), [])
    for side in ["right", "left"]:
        assert s.check(Action(look=side), [])[1] is None
