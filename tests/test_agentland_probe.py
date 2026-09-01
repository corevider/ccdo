"""A deliberately failing test, so Agentland can prove it carries CI failures back.

The branch carrying it will be deleted.
"""

def test_the_probe_fails_on_purpose():
    expected = 3
    got = 0
    assert got == expected, f"expected {expected}, got {got}"


test_the_probe_fails_on_purpose()
