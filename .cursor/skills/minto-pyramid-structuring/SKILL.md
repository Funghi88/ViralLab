---
name: minto-pyramid-structuring
description: Produces strict Minto Pyramid outputs for transcripts, interviews, and long-form content. Use when the user asks for Minto Pyramid, conclusion-first writing, MECE grouping, executive summaries, logic structuring, or wants content rewritten into Why-Impact-Path with evidence.
---
# Minto Pyramid Structuring

## Purpose
Convert messy narrative text into a strict, usable Pyramid Principle output:
- Single governing thought (answer first)
- Grouped arguments (MECE-oriented)
- Evidence mapped under each argument
- Clear logic order

## When To Apply
Apply this skill when the user asks to:
- "Use Minto Pyramid"
- "Restructure this transcript/interview"
- "Make it conclusion-first"
- "Group the logic and remove narrative dump"
- "Create executive summary / strategy brief"

## Non-Negotiable Rules
1. **Conclusion must be one sentence** and appear first.
2. **Key points must be grouped by one dimension** only (no mixed dimensions).
3. **No timeline narration** in key points unless user explicitly asks time order.
4. **Evidence must support a specific key point**, not dumped as one long list.
5. **State the logic order** used: Time, Structural, or Cause-Effect.

## Workflow
Use this checklist and complete in order:

Task Progress:
- [ ] Step 1: Extract candidate governing thought
- [ ] Step 2: Pick one logic order
- [ ] Step 3: Build 3-5 MECE key points
- [ ] Step 4: Attach supporting evidence per point
- [ ] Step 5: Run quality gate and revise

### Step 1: Governing Thought
Write one sentence that is:
- Arguable (not generic)
- Memorable (clear claim)
- Action-relevant

Bad: "The speaker talks about many things."
Good: "In the AI era, designer value shifts from execution speed to judgment and business framing."

### Step 2: Choose Logic Order
Pick exactly one:
- **Cause-Effect**: Why -> Impact -> Path
- **Structural**: Part A -> Part B -> Part C
- **Time**: Before -> During -> After

Default to **Cause-Effect** for career/strategy/pain-point content.

### Step 3: Build Key Points (MECE-Oriented)
Write 3-5 points that are:
- Mutually exclusive enough to avoid overlap
- Collectively sufficient for the conclusion
- Parallel in grammar and abstraction level

### Step 4: Map Evidence
For each key point, add 1-3 evidence bullets:
- concrete quote
- observed behavior
- case/practice
- data/fact

### Step 5: Quality Gate
Reject and rewrite if any is true:
- Conclusion is paragraph-length or vague
- Key points mix dimensions (role + time + emotion in same level)
- Evidence is not mapped to points
- Output reads as interview chronology

## Output Format
Always use this format unless user requests another:

```markdown
## Conclusion (answer first)
<one sentence governing thought>

**Logic order:** <Cause-Effect | Structural | Time>

## Key points (grouped)
1. <Point 1>
2. <Point 2>
3. <Point 3>

## Supporting evidence
### For point 1
- <evidence>
- <evidence>

### For point 2
- <evidence>

### For point 3
- <evidence>

## Rewrite direction (optional)
- <how to convert into publishable draft>
```

## Domain Preset: AI-Era Career Transition
When text is about designers/engineers and AI transition, prefer:
- Point 1: Value shift (execution commoditized)
- Point 2: Human moat (judgment, taste, framing)
- Point 3: Transition path (portfolio, offers, one-person business)

## Additional Resources
- For scoring rubric and anti-patterns, see [reference.md](reference.md)
- For concrete before/after examples, see [examples.md](examples.md)
