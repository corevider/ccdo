#!/usr/bin/env bash
# Run every test. They are redirected to a temp directory through XDG_*, so
# they never touch the real queue or registry.
cd "$(dirname "$0")" || exit 1

fail=0
for t in test_*.py; do
    PYTHONPATH="$PWD" python3 "$t" || fail=1
done

if [ "$fail" -eq 0 ]; then
    echo "ALL TESTS PASSED"
else
    echo "SOME TESTS FAILED"
fi
exit "$fail"
