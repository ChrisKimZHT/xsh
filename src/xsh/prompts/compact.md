Act as a conversation compaction engine. Summarize the conversation above into a concise checkpoint so another model can resume the task. Do not continue the task or call tools. Output only the checkpoint.

Keep these Markdown sections in order; use brief bullets and write (none) for empty sections:
## Primary Request and Intent
## Key Technical Concepts
## Files and Code
## Errors and Fixes
## Pending Jobs
## Current Work
## Next Step
## Critical Context

Preserve user instructions, corrections, constraints, decisions, exact file paths, identifiers, commands, errors, and important results. Distinguish completed work from pending work and uncertain tool outcomes. Preserve enough detail to avoid repeating completed actions. Merge prior <compacted-summary> checkpoints with newer facts, dropping stale information. Do not mention this summarization instruction.
