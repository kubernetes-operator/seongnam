# 보안 운영 가이드

| 항목 | 상태 | 문서·도구 |
|---|---|---|
| 노드 SSH 의존 제거 | **완료** — 수집기가 Prometheus 지표만 사용. 좀비 지표용 node-exporter `--collector.processes` 활성화(공용 prometheus-stack helm revision 3) | `src/collector/os_collector.py`, `deploy/monitoring/` |
| 시크릿 GitOps 편입 | 컨트롤러 설치 **완료**(kube-system, 차트 2.16.1) → **운영자가 kubeseal 설치 후 봉인·개인키 백업 필요** | `deploy/sealed-secrets/README.md`, `scripts/seal-secrets.sh` |
| GitHub 토큰 교체 | **운영자 직접 수행 필요** | 아래 절차 |

자격 증명을 만들거나, 바꾸거나, 지우는 일과 그 값을 다루는 일은 운영자가 직접 합니다.
자동화 도구나 AI 에이전트는 이 작업을 하지 않습니다. 값이 대화나 로그에 남아 다시 노출될 수 있기 때문입니다.

---

## GitHub 토큰 교체·폐기 절차

배경: 예전에 git remote URL에 classic PAT(`ghp_…`)가 평문으로 들어 있었습니다. 지금은 URL에서 제거했지만,
서버는 여전히 `~/.bashrc`의 `GITHUB_TOKEN`(classic PAT, `repo`+`workflow` 권한)으로 인증하고 있습니다.
ArgoCD는 자격 증명 없이 저장소를 읽으므로 **토큰을 폐기해도 배포에는 영향이 없습니다.**

### 1. 새 토큰 만들기 (GitHub 웹)
1. Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate new token.
2. Resource owner는 저장소를 소유한 조직, Repository access는 **이 저장소 하나만** 고릅니다.
3. Permissions는 Contents: Read and write, Metadata: Read만 줍니다. PR을 쓸 때만 Pull requests: Read and write를 추가합니다.
   GitHub Actions는 쓰지 않으므로 `workflow` 권한은 필요 없습니다.
4. Expiration은 90일처럼 **만료일을 반드시 정합니다.**

### 2. 서버의 토큰 바꾸기
```bash
vi ~/.bashrc                     # export GITHUB_TOKEN=... 줄 삭제
unset GITHUB_TOKEN               # 환경변수가 남아 있으면 gh가 저장된 자격보다 이걸 먼저 씀
read -rs NEW_TOKEN && echo "$NEW_TOKEN" | gh auth login --with-token && unset NEW_TOKEN
gh auth setup-git
ls -l ~/.config/gh/hosts.yml     # 권한이 600인지 확인
```
이미 실행 중인 셸이나 에이전트 세션은 옛 환경변수를 물려받은 상태입니다. 교체한 뒤 다시 시작하세요.

### 3. 동작 확인
```bash
gh auth status
git ls-remote origin
```

### 4. 옛 토큰 폐기
Settings → Developer settings → Personal access tokens → **Tokens (classic)**에서 예전 토큰(권한 `repo`·`workflow`)을
찾아 **Delete**를 누릅니다. 노출됐던 토큰과 서버에서 쓰던 토큰이 따로 있으면 둘 다 지웁니다. 지운 뒤 3단계를 다시 실행합니다.
새 토큰을 바로 만들 수 없다면 **폐기를 먼저** 해도 됩니다. 그동안 푸시만 잠깐 막힐 뿐입니다.

### 5. 악용 흔적 점검
- 개인 Settings → Security log, 조직 Settings → Audit log에서 노출 이후 기간의 `git.push`, `personal_access_token`, `repo.*` 이벤트를 봅니다.
- 저장소 Settings → Deploy keys / Webhooks / Collaborators에 모르는 항목이 생겼는지 봅니다.
- `git log --all --since=<노출 시점>`으로 모르는 커밋이 있는지 봅니다.
