---
name: github-actions
description: |
  GitHub Actions CI/CD 워크플로우를 작성하는 스킬. PR 시 린트·테스트·빌드 검증(CI), main 머지 시 Harbor 빌드·푸시·GitOps 태그 업데이트(CD)를 수행한다. 'GitHub Actions 설정', 'CI 워크플로우 작성', 'CD 파이프라인 구성', 'self-hosted runner', 'actions-runner-controller', 'ARC 설치', '.github/workflows 생성', 'Harbor push 자동화', '이미지 태그 업데이트 자동화' 등 CI/CD 관련 요청 시 반드시 이 스킬을 사용할 것.
---

# GitHub Actions 스킬

## 파이프라인 흐름

```
feature 브랜치 push
  → PR 생성 → [CI: ci.yml]
      ├── ruff lint
      ├── pytest 단위 테스트 (커버리지 80%)
      ├── 통합 테스트 (경고만)
      └── Docker 빌드 검증 (push 없음)
  → PR 머지 → main → [CD: cd.yml]
      ├── Harbor 이미지 빌드 + trivy 스캔 + push
      └── deploy/overlays/prod/kustomization.yaml 이미지 태그 업데이트
          → git commit [skip ci] → ArgoCD 감지 → K8s 동기화
```

---

## CI 워크플로우 (.github/workflows/ci.yml)

```yaml
name: CI

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  lint:
    name: Lint
    runs-on: arc-runner-set
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"
      - run: pip install ruff
      - run: ruff check src/ --select E,F,W,I
      - run: ruff format src/ --check

  test-unit:
    name: Unit Tests
    runs-on: arc-runner-set
    needs: lint
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"
      - run: pip install -r requirements.txt pytest pytest-asyncio pytest-cov
      - run: |
          pytest tests/unit/ -v \
            --cov=src/ \
            --cov-report=term-missing \
            --cov-fail-under=80

  test-integration:
    name: Integration Tests
    runs-on: arc-runner-set   # K8s 내부 → Prometheus/Loki DNS 접근 가능
    needs: lint
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"
      - run: pip install -r requirements.txt pytest pytest-asyncio
      - env:
          DATABASE_URL: ${{ secrets.TEST_DATABASE_URL }}
        run: pytest tests/integration/ -m integration -v --tb=short
        continue-on-error: true   # 인프라 문제 시 경고만

  build-check:
    name: Docker Build Check
    runs-on: arc-runner-set
    needs: [test-unit]
    steps:
      - uses: actions/checkout@v4
      - run: docker build -f Dockerfile.api -t k8s-monitor/api:check .
      - run: docker build -f Dockerfile.collector -t k8s-monitor/collector:check .
      - run: docker build -f Dockerfile.dashboard -t k8s-monitor/dashboard:check .
```

---

## CD 워크플로우 (.github/workflows/cd.yml)

```yaml
name: CD

on:
  push:
    branches: [main]
    paths:
      - 'src/**'
      - 'dashboard/**'
      - 'Dockerfile.*'
      - 'requirements.txt'

jobs:
  build-and-push:
    name: Build & Push to Harbor
    runs-on: arc-runner-set
    outputs:
      git-sha: ${{ steps.meta.outputs.sha }}

    steps:
      - uses: actions/checkout@v4

      - name: Set image metadata
        id: meta
        run: echo "sha=$(git rev-parse --short HEAD)" >> "$GITHUB_OUTPUT"

      - uses: docker/login-action@v3
        with:
          registry: ${{ secrets.HARBOR_REGISTRY }}
          username: ${{ secrets.HARBOR_USERNAME }}
          password: ${{ secrets.HARBOR_PASSWORD }}

      - uses: docker/setup-buildx-action@v3

      - uses: docker/build-push-action@v5
        with:
          file: Dockerfile.api
          push: true
          tags: |
            ${{ secrets.HARBOR_REGISTRY }}/k8s-monitor/api:${{ steps.meta.outputs.sha }}
            ${{ secrets.HARBOR_REGISTRY }}/k8s-monitor/api:latest
          cache-from: type=registry,ref=${{ secrets.HARBOR_REGISTRY }}/k8s-monitor/api:cache
          cache-to: type=registry,ref=${{ secrets.HARBOR_REGISTRY }}/k8s-monitor/api:cache,mode=max

      - uses: docker/build-push-action@v5
        with:
          file: Dockerfile.collector
          push: true
          tags: |
            ${{ secrets.HARBOR_REGISTRY }}/k8s-monitor/collector:${{ steps.meta.outputs.sha }}
            ${{ secrets.HARBOR_REGISTRY }}/k8s-monitor/collector:latest

      - uses: docker/build-push-action@v5
        with:
          file: Dockerfile.dashboard
          push: true
          tags: |
            ${{ secrets.HARBOR_REGISTRY }}/k8s-monitor/dashboard:${{ steps.meta.outputs.sha }}
            ${{ secrets.HARBOR_REGISTRY }}/k8s-monitor/dashboard:latest

      - uses: aquasecurity/trivy-action@master
        with:
          image-ref: ${{ secrets.HARBOR_REGISTRY }}/k8s-monitor/api:${{ steps.meta.outputs.sha }}
          severity: HIGH,CRITICAL
          exit-code: 1

  update-gitops:
    name: Update GitOps image tags
    runs-on: arc-runner-set
    needs: build-and-push

    steps:
      - uses: actions/checkout@v4
        with:
          token: ${{ secrets.GITHUB_TOKEN }}

      - name: Update kustomization image tags
        env:
          SHA: ${{ needs.build-and-push.outputs.git-sha }}
          REG: ${{ secrets.HARBOR_REGISTRY }}
        run: |
          cd deploy/overlays/prod
          kustomize edit set image \
            k8s-monitor/api=${REG}/k8s-monitor/api:${SHA} \
            k8s-monitor/collector=${REG}/k8s-monitor/collector:${SHA} \
            k8s-monitor/dashboard=${REG}/k8s-monitor/dashboard:${SHA}

      - name: Commit and push
        env:
          SHA: ${{ needs.build-and-push.outputs.git-sha }}
        run: |
          git config user.name "kwlee"
          git config user.email "blackrusiper@gmail.com"
          git add deploy/overlays/prod/kustomization.yaml
          git diff --staged --quiet || git commit -m "chore: deploy image ${SHA} [skip ci]"
          git push origin main
```

---

## Actions Runner Controller (ARC) 설치

K8s 클러스터 내부 self-hosted runner. 외부 GitHub-hosted runner 불사용.

```bash
# ARC 컨트롤러 설치
helm install arc \
  oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set-controller \
  --namespace arc-systems --create-namespace

# Runner Scale Set 설치
# GITHUB_PAT: repo scope 필요
helm install arc-runner-set \
  oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set \
  --namespace arc-runners --create-namespace \
  --set githubConfigUrl=https://github.com/kubernetes-operator/seongnam \
  --set githubConfigSecret.github_token=${GITHUB_PAT} \
  --set minRunners=1 \
  --set maxRunners=5
```

워크플로우에서 `runs-on: arc-runner-set`으로 지정한다.

---

## 필요한 GitHub Secrets

| Secret | 내용 |
|--------|------|
| `HARBOR_REGISTRY` | Harbor 레지스트리 주소 (예: `harbor.example.com`) |
| `HARBOR_USERNAME` | Harbor 로그인 사용자명 |
| `HARBOR_PASSWORD` | Harbor 로그인 비밀번호 |
| `TEST_DATABASE_URL` | 테스트용 TimescaleDB 연결 URL |

Settings → Secrets and variables → Actions 에서 등록.
코드·설정 파일에는 절대 포함하지 않는다.

---

## 브랜치 보호 규칙

GitHub → Settings → Branches → main:
- **Require a pull request before merging** (직접 push 차단)
- **Require status checks to pass**: `lint`, `test-unit`, `build-check`
- **Dismiss stale reviews on new push**
