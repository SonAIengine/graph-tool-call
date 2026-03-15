# graph-tool-call demo — 4 scenarios
Output assets/demo.gif
Set Shell zsh
Set FontSize 16
Set FontFamily "JetBrains Mono"
Set Width 1100
Set Height 520
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
Set TypingSpeed 45ms
Set Theme "TokyoNight"

Hide
Type "export PATH=/Users/sonseongjun/Projects/personal/graph-tool-call/.venv/bin:$PATH"
Enter
Sleep 500ms
Type "cd /Users/sonseongjun/Projects/personal/graph-tool-call"
Enter
Sleep 500ms
Type "clear"
Enter
Sleep 300ms
Show

# === Scenario 1: Search 248 K8s API tools ===
Sleep 500ms
Type "graph-tool-call search 'delete a pod' --source benchmarks/specs/k8s_core_v1.json --scores"
Enter
Sleep 8s
Sleep 3s

Hide
Type "clear"
Enter
Sleep 300ms
Show

# === Scenario 2: Token savings — K8s (248 tools) ===
Sleep 500ms
Type "python examples/token_savings_demo.py benchmarks/specs/k8s_core_v1.json 'delete a pod'"
Enter
Sleep 6s
Sleep 3s

Hide
Type "clear"
Enter
Sleep 300ms
Show

# === Scenario 3: Token savings — GitHub API (58 tools) ===
Sleep 500ms
Type "python examples/token_savings_demo.py benchmarks/specs/github_subset.json 'create a pull request'"
Enter
Sleep 6s
Sleep 3s

Hide
Type "clear"
Enter
Sleep 300ms
Show

# === Scenario 4: Ingest + Graph Info ===
Sleep 500ms
Type "graph-tool-call ingest benchmarks/specs/petstore3.json -o /tmp/petstore.json --organize"
Enter
Sleep 4s
Sleep 1s

Type "graph-tool-call info /tmp/petstore.json"
Enter
Sleep 3s
Sleep 3s
