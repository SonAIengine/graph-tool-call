# Bonsai-8B (1-bit Q1_0)

> Tested: 2026-04-07 | Runtime: llama.cpp | API: OpenAI-compatible (`localhost:8080`)

## Model Spec

| Item | Value |
|------|-------|
| Parameters | 8B |
| Quantization | Q1_0 (1-bit) |
| File Size | 1.1 GB |
| Memory Usage | ~1.7 GB |
| Prompt Speed | 58 tok/s |
| Generation Speed | 31 tok/s |
| Context Window | 8192 (default) |

## Results Summary

| Dataset | Tools | Queries | Baseline Acc | Retrieve Acc | Delta | Token Reduction | Recall@5 | p-value |
|---------|------:|--------:|-------------:|-------------:|------:|----------------:|---------:|--------:|
| Petstore 3.0 | 19 | 23 | 65.2% | 56.5% | -8.7% | 68.4% | 98.6% | 0.3283 (ns) |
| Mixed MCP | 38 | 30 | 0.0% | 73.3% | **+73.3%** | N/A | 93.3% | <0.0001 (***) |

## Petstore 3.0 (19 tools, 23 queries)

### Metrics

| Metric | Baseline | Retrieve (top-5) |
|--------|---------|-----------------|
| Tool Accuracy | 65.2% (15/23) | 56.5% (13/23) |
| Avg Input Tokens | 1,875 | 601 |
| Token Reduction | — | 68.4% |
| Token Efficiency | 0.35 | 0.95 |
| Avg Latency | 1,897 ms | 3,877 ms |

### Per-Query Results

| # | Query | Difficulty | Baseline | Retrieve | Notes |
|---|-------|-----------|----------|----------|-------|
| 1 | Find all available pets | easy | findPetsByStatus | findPetsByStatus | |
| 2 | Add a new dog to the pet store | easy | addPet | **None** | retrieve: tool call 미생성 |
| 3 | Get pet with ID 42 | easy | getPetById | getPetById | |
| 4 | Update the name of my pet | medium | **None** | **None** | 양쪽 실패 |
| 5 | Delete pet number 7 | easy | deletePet | deletePet | |
| 6 | Search pets by their tags | medium | findPetsByTags | findPetsByTags | |
| 7 | Upload a photo of my pet | medium | **None** | **None** | 양쪽 실패 |
| 8 | Check the store inventory | easy | getInventory | getInventory | |
| 9 | Place an order to buy a pet | easy | **None** | **None** | 양쪽 실패 |
| 10 | Look up order number 5 | easy | getOrderById | getOrderById | |
| 11 | Cancel my order | easy | **None** | **None** | 양쪽 실패 |
| 12 | Create a new user account | easy | createUser | **None** | retrieve: tool call 미생성 |
| 13 | Sign in with username and password | easy | loginUser | loginUser | |
| 14 | Log out of my account | easy | logoutUser | logoutUser | |
| 15 | View user profile for john123 | easy | getUserByName | getUserByName | |
| 16 | Change user email address | medium | **None** | **None** | 양쪽 실패 |
| 17 | Remove user john123 | easy | deleteUser | deleteUser | |
| 18 | Create multiple user accounts at once | medium | **None** | createUsersWithListInput | retrieve만 성공 |
| 19 | Show me sold pets | easy | findPetsByStatus | findPetsByStatus | |
| 20 | Adopt a pet (workflow) | hard | **None** | **None** | 양쪽 실패 |
| 21 | Update pet using form data | hard | updatePetWithForm | updatePetWithForm | |
| 22 | What pets are in the store? | medium | **None** | **None** | 양쪽 실패 |
| 23 | Remove a pet listing and delete order | hard | deletePet | **None** | retrieve: tool call 미생성 |

## Mixed MCP Servers (38 tools, 30 queries)

### Metrics

| Metric | Baseline | Retrieve (top-5) |
|--------|---------|-----------------|
| Tool Accuracy | 0.0% (0/30) | 73.3% (22/30) |
| Avg Input Tokens | N/A (all failed) | 682 |
| Avg Latency | N/A | 4,509 ms |
| Token Efficiency | 0.00 | 1.06 |

### Per-Query Results

| # | Query | Difficulty | Retrieve | Notes |
|---|-------|-----------|----------|-------|
| 1 | Read the contents of config.yaml | easy | read_file | |
| 2 | Write a new configuration file | easy | write_file | |
| 3 | List all files in the src directory | easy | list_directory | |
| 4 | Create the output directory | easy | create_directory | |
| 5 | Find all Python files in the project | easy | search_files | |
| 6 | Move the old log file to archive | easy | move_file | |
| 7 | Check the file size and permissions | easy | get_file_info | |
| 8 | Show the directory tree structure | easy | directory_tree | |
| 9 | Edit the import statement in main.py | medium | edit_file | |
| 10 | Read multiple config files at once | medium | read_multiple_files | |
| 11 | Create a new issue for the bug | easy | **None** | retrieval OK, tool call 미생성 |
| 12 | Open a pull request for my changes | medium | **None** | retrieval miss (recall=0) |
| 13 | Search for repos about ML | easy | search_repositories | |
| 14 | Fork the upstream repository | medium | **None** | retrieval OK, tool call 미생성 |
| 15 | List all open issues with bug label | easy | list_issues | |
| 16 | Get the README from the GitHub repo | medium | get_file_contents | |
| 17 | Merge the feature branch PR | medium | **None** | retrieval OK, tool call 미생성 |
| 18 | Comment on the PR with review feedback | medium | **None** | retrieval miss (recall=0) |
| 19 | Create a new branch for the feature | easy | create_branch | |
| 20 | Push the updated files to GitHub | medium | **None** | retrieval OK, tool call 미생성 |
| 21 | Search code for the function definition | medium | search_code | |
| 22 | Which directories can the file server access? | hard | list_allowed_directories | |
| 23 | Check details of PR number 55 | easy | get_pull_request | |
| 24 | Approve the pull request after review | medium | **None** | retrieval OK, tool call 미생성 |
| 25 | View the commit history | easy | list_commits | |
| 26 | Create a new GitHub repo and initialize it | easy | create_repository | |
| 27 | Update the issue title and close it | medium | update_issue | |
| 28 | See what files were changed in PR 10 | easy | get_pull_request_files | |
| 29 | Find all TypeScript files matching *.test.ts | easy | search_files | |
| 30 | Create a file on GitHub with deploy config | medium | create_repository | wrong tool (expected: create_or_update_file) |

## Failure Analysis

### 1. Tool Call 미생성 (None) — 가장 빈번한 실패 패턴

Bonsai-8B는 도구를 **잘못 고르는** 것이 아니라, tool call JSON을 **아예 생성하지 못하는** 경우가 대부분이다. 텍스트로 응답하거나 빈 응답을 반환한다.

- Petstore baseline: 8/23 (34.8%) None
- Petstore retrieve: 10/23 (43.5%) None
- Mixed MCP baseline: 30/30 (100%) None
- Mixed MCP retrieve: 7/30 (23.3%) None

### 2. Baseline 완전 실패 (Mixed MCP)

38개 도구를 전부 context에 넣으면 input tokens가 과다해져 tool call 자체를 포기한다. 1-bit 양자화 모델의 long context 처리 한계.

### 3. Write 작업 취약

tool call 미생성 실패가 write/create 계열에 집중:
- `placeOrder`, `addPet`, `uploadFile`, `fork_repository`, `push_files` 등
- read 계열은 상대적으로 안정적 (getPetById, getInventory 등)

### 4. Retrieve가 Baseline보다 낮은 Petstore

19개 도구는 Bonsai-8B가 감당 가능한 수준이라 baseline이 소폭 우위 (65.2% vs 56.5%).
하지만 retrieve 모드에서 `createUsersWithListInput` 같은 세밀한 선택에 성공한 케이스도 있다.

## Key Insight

> **도구 수가 많아질수록 graph-tool-call의 retrieval 필터링은 필수적이다.**
> 38개 도구만으로도 Bonsai-8B baseline은 0%로 완전히 무너지지만,
> top-5 필터링 시 73.3%까지 복구된다. (p < 0.0001)
>
> 1-bit 양자화 소형 모델에서 graph-tool-call의 가치가 가장 극명하게 드러난다.

## Raw Data

- Petstore: `benchmarks/results/benchmark_e2e_20260407_014809.json`
- Mixed MCP: `benchmarks/results/benchmark_e2e_20260407_015032.json`
