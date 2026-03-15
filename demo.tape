# graph-tool-call demo — 3 scenarios
Output assets/demo.gif
Set Shell zsh
Set FontSize 18
Set Width 1100
Set Height 500
Set Padding 20
Set TypingSpeed 45ms
Set Theme "Dracula"

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

# === Scenario 2: Ingest + Info ===
Sleep 500ms
Type "graph-tool-call ingest benchmarks/specs/petstore3.json -o /tmp/petstore.json --organize"
Enter
Sleep 4s
Sleep 1s

Type "graph-tool-call info /tmp/petstore.json"
Enter
Sleep 3s
Sleep 2s

Hide
Type "clear"
Enter
Sleep 300ms
Show

# === Scenario 3: Search + Dry-run API call ===
Sleep 500ms
Type `graph-tool-call call 'find pet by id' --source benchmarks/specs/petstore3.json --base-url https://petstore3.swagger.io/api/v3 --args '{"petId": 1}' --dry-run`
Enter
Sleep 5s
Sleep 3s
