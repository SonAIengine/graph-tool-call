# graph-tool-call demo — 3 scenarios
Output assets/demo.gif
Set Shell bash
Set FontSize 15
Set Width 1100
Set Height 550
Set Padding 20
Set Margin 12
Set MarginFill "#1a1b26"
Set BorderRadius 10
Set WindowBar Colorful
Set WindowBarSize 36
Set LetterSpacing 0
Set LineHeight 1.3
Set CursorBlink false
Set Framerate 30
Set PlaybackSpeed 1
Set TypingSpeed 40ms
Set Theme "TokyoNight"

Hide
Type "export PATH=/home/son/projects/app/graph-tool-call/.venv/bin:$PATH"
Enter
Sleep 500ms
Type "cd /home/son/projects/app/graph-tool-call"
Enter
Sleep 500ms
Type "clear"
Enter
Sleep 300ms
Show

# ━━━ Scenario 1: Token Savings ━━━
Sleep 300ms
Type "echo ''"
Enter
Type "echo '  ━━━ 1. Token Savings: 248 K8s API tools ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'"
Enter
Type "echo '  LLMs choke on 248 tool definitions. graph-tool-call picks only what matters.'"
Enter
Type "echo ''"
Enter
Sleep 1.5s

Type "python examples/token_savings_demo.py benchmarks/specs/k8s_core_v1.json 'scale my deployment and check health'"
Enter
Sleep 8s
Sleep 3s

Hide
Type "clear"
Enter
Sleep 300ms
Show

# ━━━ Scenario 2: Workflow Search — E-Commerce ━━━
Sleep 300ms
Type "echo ''"
Enter
Type "echo '  ━━━ 2. Workflow Search: E-Commerce (46 tools) ━━━━━━━━━━━━━━━━━━━━━━━━'"
Enter
Type "echo '  Vector search finds cancelOrder. graph-tool-call finds the full workflow.'"
Enter
Type "echo ''"
Enter
Sleep 1.5s

Type "graph-tool-call search 'cancel my order and get a refund' --source tests/fixtures/ecommerce_openapi.json --scores"
Enter
Sleep 6s
Sleep 3s

Hide
Type "clear"
Enter
Sleep 300ms
Show

# ━━━ Scenario 3: Developer Workflow — GitHub API ━━━
Sleep 300ms
Type "echo ''"
Enter
Type "echo '  ━━━ 3. Developer Workflow: GitHub API (58 tools) ━━━━━━━━━━━━━━━━━━━━━━'"
Enter
Type "echo '  Every developer knows this flow. graph-tool-call finds it automatically.'"
Enter
Type "echo ''"
Enter
Sleep 1.5s

Type "graph-tool-call search 'review and merge a pull request' --source benchmarks/specs/github_subset.json --scores"
Enter
Sleep 6s
Sleep 3s
