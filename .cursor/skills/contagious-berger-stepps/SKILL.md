---
name: contagious-berger-stepps
description: Applies Jonah Berger STEPPS as a strict, auditable contagious-content evaluation workflow. Use when scoring articles/videos/posts for shareability, ranking inspiration candidates, or when the user asks for STEPPS-based content diagnosis and rewrite guidance.
---
# Contagious Berger STEPPS

## Objective
Evaluate content with a disciplined STEPPS lens so outputs are:
- comparable across items
- explainable (signal by signal)
- actionable for rewrite

## When To Use
- "Evaluate contagiousness"
- "Use Berger STEPPS strictly"
- "Rank which articles attract attention"
- "Tell me what to learn from these posts"

## Mandatory Evaluation Rules
1. Score all six STEPPS principles every time.
2. Keep principle scores separate; do not collapse into vague sentiment.
3. Report top 2 strong signals and weakest signal.
4. Provide one concrete rewrite action for weakest signal.
5. If evidence is thin, mark confidence low instead of inflating score.

## Workflow
Task Progress:
- [ ] Step 1: Parse item text (title + snippet/body)
- [ ] Step 2: Score six principles
- [ ] Step 3: Compute total + diversity check
- [ ] Step 4: Generate diagnosis (strongest/weakest)
- [ ] Step 5: Output ranking + inspiration notes

## Output Contract
```markdown
## STEPPS Score
- Total: <0-100>
- Social Currency: <0-20>
- Triggers: <0-20>
- Emotion: <0-20>
- Public: <0-20>
- Practical Value: <0-20>
- Stories: <0-20>

## Diagnosis
- Strongest: <signal 1> + <signal 2>
- Weakest: <signal>
- Rewrite action: <one concrete change>

## Inspiration Value
- Why this item is worth borrowing from: <1-2 bullets>
```

## Quality Gate
Reject output if:
- only total score is shown
- no weakest-signal action
- labels mismatch STEPPS terminology

## Additional Resources
- Scoring details and guardrails: [reference.md](reference.md)
- Examples: [examples.md](examples.md)
