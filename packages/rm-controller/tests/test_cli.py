"""Use explicit flags so Helm's apply/namespace permissions match the running controller."""
import pytest

from rm_controller import controller


@pytest.mark.parametrize("flag", ["--app", "--namesp=elsewhere"])
def test_abbreviated_operational_flags_are_rejected_before_loading_spec(flag, capsys):
    with pytest.raises(SystemExit) as error:
        controller.main(["--spec", "not-loaded.yaml", "--once", flag])
    assert error.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err
