"""A deliberately failing test, so Agentland can prove it tells the agent why.

The branch carrying it will be deleted.
"""

def test_the_probe_fails_on_purpose():
    expected = "the port probe reads the range once"
    got = "it reads it twice on a cold start"
    assert got == expected, f"expected {expected!r}, got {got!r}"


test_the_probe_fails_on_purpose()
