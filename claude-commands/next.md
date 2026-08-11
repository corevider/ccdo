---
description: take the next task from the ccdo queue and do it
allowed-tools: Bash(ccdo:*)
---

The next task pulled from this session's queue:

!`ccdo next`

Do the task above. If the output is empty, tell the user the queue is empty and
stop. If the task references a file path, read that file first.
When you are done, suggest running `ccdo done <id>`.

Note: `ccdo next` picks this session's queue by looking at the working
directory, and hands over tasks the user marked by hand in the window first.
