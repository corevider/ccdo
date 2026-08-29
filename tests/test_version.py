#!/usr/bin/env python3
"""Version comparison and the update check.

Checking for updates must never get in the way: with the network down, with a
malformed answer from GitHub, or with the user having switched it off, it has
to pass quietly. A wrong comparison would also nag "update available" forever.
"""
import json
import os
import time

from harness import jd, Results, CFG

r = Results("version and updates")

r.check(jd.parse_version("v1.2.3") == (1, 2, 3), "the v prefix is ignored")
r.check(jd.parse_version("1.2") == (1, 2, 0), "a missing part counts as zero")
r.check(jd.parse_version("") == (0, 0, 0), "an empty value is zero")
r.check(jd.parse_version("bozuk") == (0, 0, 0), "a value with no digits is zero")

r.check(jd.newer_version("1.0.1", "1.0.0") is True, "a patch release is newer")
r.check(jd.newer_version("1.1.0", "1.0.9") is True, "a minor release compares correctly")
r.check(jd.newer_version("v1.0.0", "1.0.0") is False, "the same version is not newer")
r.check(jd.newer_version("0.9.9", "1.0.0") is False, "an older version is not newer")
r.check(jd.newer_version("", "1.0.0") is False, "an empty value raises no nag")
r.check(jd.newer_version(None, "1.0.0") is False, "None raises no nag")
r.check(jd.newer_version("1.0.10", "1.0.9") is True,
        "numeric comparison (as text 1.0.10 would sort below 1.0.9)")


def clean():
    try:
        os.unlink(jd.UPDATE_PATH)
    except OSError:
        pass


def fake_network(result):
    """Swap out urlopen so the routes are exercised without a real network."""
    real = jd.urllib.request.urlopen

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            if isinstance(result, Exception):
                raise result
            return json.dumps(result).encode()

    def fake(req, timeout=None):
        if isinstance(result, Exception):
            raise result
        return Response()

    jd.urllib.request.urlopen = fake
    return real


# ----------------------------------------------------------------- check

clean()
real = fake_network({"tag_name": "v9.9.9"})
try:
    cache = jd.check_update(CFG, force=True)
finally:
    jd.urllib.request.urlopen = real
r.check(cache.get("latest") == "v9.9.9", "the release tag is read", str(cache))
r.check(jd.read_update_cache().get("latest") == "v9.9.9", "the result was cached")

# The second call must not reach the network: the cache is fresh.
real = fake_network(OSError("should not have reached the network"))
try:
    cache = jd.check_update(CFG)
finally:
    jd.urllib.request.urlopen = real
r.check(cache.get("latest") == "v9.9.9", "within a day we do not reach out again")

# A network error: the previous answer must survive, nothing may crash.
real = fake_network(OSError("no network"))
try:
    cache = jd.check_update(CFG, force=True)
finally:
    jd.urllib.request.urlopen = real
r.check(cache.get("latest") == "v9.9.9", "the old answer survives a network error")
r.check(float(cache.get("checked_at", 0)) > time.time() - 60,
        "the stamp is updated despite the error (so it stops retrying)")

# With the user having switched it off, we must not look at all.
clean()
real = fake_network(OSError("must not reach the network while switched off"))
try:
    cache = jd.check_update(dict(CFG, check_updates=False), force=True)
finally:
    jd.urllib.request.urlopen = real
r.check(cache == {}, "with check_updates off we do not reach the network", str(cache))
r.check(not os.path.exists(jd.UPDATE_PATH), "switched off, nothing is cached either")

# A malformed cache file must not crash anything.
jd.atomic_write(jd.UPDATE_PATH, "{malformed json")
r.check(jd.read_update_cache() == {}, "a malformed cache yields an empty dict")
clean()

r.check(jd.REPO in jd.update_command() and "curl" in jd.update_command(),
        "the update command points at the repo", jd.update_command())
r.check("check_updates" in jd.DEFAULT_CONFIG, "the setting is defined in the defaults")

clean()
real = fake_network({"tag_name": "v9.9.9"})
try:
    jd.check_update(CFG, force=True)
finally:
    jd.urllib.request.urlopen = real

# The tray's hourly timer forces its way past the cache: a fresh cache used
# to mean the tray re-read yesterday's answer for a whole day.
real = fake_network({"tag_name": "v9.9.10"})
try:
    cache = jd.check_update(CFG, force=True)
finally:
    jd.urllib.request.urlopen = real
r.check(cache.get("latest") == "v9.9.10", "a forced check goes past a fresh cache")

title, body = jd.update_notice("v9.9.10")
r.check("v9.9.10" in title and jd.VERSION in title,
        "the notification names both versions", title)
r.check(bool(body.strip()), "the notification says what to do next")

raise SystemExit(r.finish())
