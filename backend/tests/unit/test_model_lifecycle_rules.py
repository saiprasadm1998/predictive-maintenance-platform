"""The version state model of ARC Figure 7: every action from every status."""

from __future__ import annotations

import pytest

from pmp.modelling import Action, ModelError, VersionStatus
from pmp.modelling.lifecycle import next_status

S = VersionStatus
ALLOWED = {
    (Action.DEPLOY, S.VALIDATED): S.DEPLOYED,
    (Action.PAUSE, S.DEPLOYED): S.PAUSED,
    (Action.RESUME, S.PAUSED): S.DEPLOYED,
    (Action.RETIRE, S.DEPLOYED): S.RETIRED,
    (Action.RETIRE, S.PAUSED): S.RETIRED,
    (Action.REJECT, S.VALIDATED): S.DRAFT,
}


@pytest.mark.parametrize("action", list(Action))
@pytest.mark.parametrize("status", list(VersionStatus))
def test_every_action_from_every_status(action: Action, status: VersionStatus) -> None:
    expected = ALLOWED.get((action, status))
    if expected is not None:
        assert next_status(status, action, 3) is expected
    else:
        with pytest.raises(ModelError, match=f"Cannot {action.value} version 3: it is"):
            next_status(status, action, 3)


def test_messages_say_what_is_allowed() -> None:
    with pytest.raises(ModelError, match="only a Validated version can be deployed"):
        next_status(S.DRAFT, Action.DEPLOY, 1)
    with pytest.raises(ModelError, match="only a Deployed or Paused version can be retired"):
        next_status(S.VALIDATED, Action.RETIRE, 1)
