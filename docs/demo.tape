# Render the README demo GIF with: vhs docs/demo.tape
# (install vhs: https://github.com/charmbracelet/vhs)
# Self-contained — needs no running agent.

Output docs/demo.gif

Set Shell "bash"
Set FontSize 17
Set Width 1280
Set Height 760
Set Padding 18
Set TypingSpeed 30ms

Type "# Coehoorn sieges a (deliberately-flawed) tool-using agent..."
Enter
Type "uv run python scripts/build_tool_sample.py"
Enter
Sleep 4s

Type "# ...and catches the destructive tool call + the refund-without-approval,"
Enter
Type "# each cited to the exact turn (OWASP Agentic ASI02 / ASI03)."
Enter
Sleep 2s

Type "# Now: it grades its OWN judge against an adversarial gold set —"
Enter
Type "uv run coehoorn meta-eval --gold tests/gold/judge_gold.jsonl --rubric examples/rubric_coach.yaml"
Enter
Sleep 4s

Type "# Honest 0.66 balanced accuracy with Wilson intervals, beating the dumb baselines."
Enter
Type "# No API key, fully offline, byte-reproducible."
Enter
Sleep 3s
