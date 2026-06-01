from loihi_planner.backend_check import check_brian2loihi_available


def test_backend_check_does_not_crash():
    result = check_brian2loihi_available()
    assert {"available", "brian2_version", "brian2loihi_version", "error"} <= set(result)
    assert isinstance(result["available"], bool)
    if not result["available"]:
        assert result["error"]
