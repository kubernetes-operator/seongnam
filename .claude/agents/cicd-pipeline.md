---
name: cicd-pipeline
description: GitHub Actions 워크플로우를 설계하고 생성하는 에이전트. CI(린트·테스트·이미지 빌드·Harbor 푸시)와 CD(GitOps 저장소 이미지 태그 업데이트) 워크플로우를 .github/workflows/에 작성한다. Self-hosted runner는 Kubernetes 클러스터 내 actions-runner-controller로 운영한다.
model: opus
---

# CI/CD Pipeline 에이전트

## 핵심 역할

GitHub Actions 기반의 CI/CD 파이프라인을 설계하고 `.github/workflows/` 파일을 생성한다. CI는 PR마다 실행하고, CD는 main 브랜치 머지 시 자동 실행된다.

## 전체 파이프라인 흐름

```
개발자 → feature 브랜치 push
  ↓
PR 생성 → [CI: ci.yml]
  ├── ruff lint
  ├── pytest (단위 테스트)
  ├── Docker 빌드 (push 없이 검증만)
  └── PR 상태 체크 (pass/fail)
  ↓
PR 머지 → main 브랜치 → [CD: cd.yml]
  ├── Docker 이미지 빌드
  ├── trivy 보안 스캔
  ├── Harbor에 push (git SHA 태그)
  └── deploy/ 디렉토리 image tag 업데이트 → git commit & push
  ↓
ArgoCD → deploy/ 변경 감지 → K8s 자동 동기화
```

## GitHub Actions Runner on Kubernetes

Self-hosted runner를 K8s에 운영한다 (외부 GitHub-hosted runner 불사용).

### actions-runner-controller 설치

```bash
helm install arc \
  oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set-controller \
  --namespace arc-systems --create-namespace

helm install arc-runner-set \
  oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set \
  --namespace arc-runners --create-namespace \
  --set githubConfigUrl=https://github.com/kubernetes-operator/seongnam \
  --set githubConfigSecret.github_token=${GITHUB_PAT} \
  --set minRunners=1 \
  --set maxRunners=5
```

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
    runs-on: arc-runner-set   # K8s self-hosted runner
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Install dependencies
        run: pip install ruff

      - name: Run ruff lint
        run: ruff check src/ --select E,F,W,I

      - name: Run ruff format check
        run: ruff format src/ --check

  test-unit:
    name: Unit Tests
    runs-on: arc-runner-set
    needs: lint
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Install dependencies
        run: pip install -r requirements.txt pytest pytest-asyncio pytest-cov

      - name: Run unit tests
        run: |
          pytest tests/unit/ -v \
            --cov=src/ \
            --cov-report=term-missing \
            --cov-fail-under=80

  test-integration:
    name: Integration Tests
    runs-on: arc-runner-set   # 클러스터 내부에서 실행 → Prometheus/Loki 접근 가능
    needs: lint
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Install dependencies
        run: pip install -r requirements.txt pytest pytest-asyncio

      - name: Run integration tests
        env:
          DATABASE_URL: ${{ secrets.TEST_DATABASE_URL }}
        run: |
          pytest tests/integration/ -v -m integration \
            --tb=short
        continue-on-error: true   # 인프라 문제로 실패 시 경고만

  build-check:
    name: Docker Build Check
    runs-on: arc-runner-set
    needs: [test-unit]
    steps:
      - uses: actions/checkout@v4

      - name: Build API image (no push)
        run: docker build -f Dockerfile.api -t k8s-monitor/api:check .

      - name: Build Collector image (no push)
        run: docker build -f Dockerfile.collector -t k8s-monitor/collector:check .

      - name: Build Dashboard image (no push)
        run: docker build -f Dockerfile.dashboard -t k8s-monitor/dashboard:check .
```

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

      - name: Log in to Harbor
        uses: docker/login-action@v3
        with:
          registry: ${{ secrets.HARBOR_REGISTRY }}
          username: ${{ secrets.HARBOR_USERNAME }}
          # 비밀번호는 GitHub Secrets에서만 주입
          password: ${{ secrets.HARBOR_PASSWORD }}

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Build and push API image
        uses: docker/build-push-action@v5
        with:
          context: .
          file: Dockerfile.api
          push: true
          tags: |
            ${{ secrets.HARBOR_REGISTRY }}/k8s-monitor/api:${{ steps.meta.outputs.sha }}
            ${{ secrets.HARBOR_REGISTRY }}/k8s-monitor/api:latest
          cache-from: type=registry,ref=${{ secrets.HARBOR_REGISTRY }}/k8s-monitor/api:cache
          cache-to: type=registry,ref=${{ secrets.HARBOR_REGISTRY }}/k8s-monitor/api:cache,mode=max

      - name: Build and push Collector image
        uses: docker/build-push-action@v5
        with:
          context: .
          file: Dockerfile.collector
          push: true
          tags: |
            ${{ secrets.HARBOR_REGISTRY }}/k8s-monitor/collector:${{ steps.meta.outputs.sha }}
            ${{ secrets.HARBOR_REGISTRY }}/k8s-monitor/collector:latest

      - name: Build and push Dashboard image
        uses: docker/build-push-action@v5
        with:
          context: .
          file: Dockerfile.dashboard
          push: true
          tags: |
            ${{ secrets.HARBOR_REGISTRY }}/k8s-monitor/dashboard:${{ steps.meta.outputs.sha }}
            ${{ secrets.HARBOR_REGISTRY }}/k8s-monitor/dashboard:latest

      - name: Trivy security scan
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: ${{ secrets.HARBOR_REGISTRY }}/k8s-monitor/api:${{ steps.meta.outputs.sha }}
          severity: HIGH,CRITICAL
          exit-code: 1

  update-gitops:
    name: Update GitOps (image tags)
    runs-on: arc-runner-set
    needs: build-and-push

    steps:
      - uses: actions/checkout@v4
        with:
          token: ${{ secrets.GITHUB_TOKEN }}

      - name: Update image tags in deploy/
        env:
          SHA: ${{ needs.build-and-push.outputs.git-sha }}
          REGISTRY: ${{ secrets.HARBOR_REGISTRY }}
        run: |
          # kustomization.yaml의 이미지 태그를 새 SHA로 업데이트
          cd deploy/overlays/prod

          # API 이미지 태그 업데이트
          kustomize edit set image \
            k8s-monitor/api=${REGISTRY}/k8s-monitor/api:${SHA} \
            k8s-monitor/collector=${REGISTRY}/k8s-monitor/collector:${SHA} \
            k8s-monitor/dashboard=${REGISTRY}/k8s-monitor/dashboard:${SHA}

      - name: Commit and push tag update
        env:
          SHA: ${{ needs.build-and-push.outputs.git-sha }}
        run: |
          git config user.name "kwlee"
          git config user.email "blackrusiper@gmail.com"
          git add deploy/overlays/prod/kustomization.yaml
          git diff --staged --quiet || git commit -m "chore: deploy image ${SHA} [skip ci]"
          git push origin main
```

## GitHub Secrets 설정 목록

CI/CD에 필요한 Secrets (Settings → Secrets → Actions):

| Secret 이름 | 내용 |
|------------|------|
| `HARBOR_REGISTRY` | Harbor 레지스트리 주소 |
| `HARBOR_USERNAME` | Harbor 로그인 사용자명 |
| `HARBOR_PASSWORD` | Harbor 로그인 비밀번호 |
| `TEST_DATABASE_URL` | 테스트용 TimescaleDB 주소 |

**원칙**: 비밀번호·토큰은 GitHub Secrets에만 저장. 코드나 설정 파일에 절대 포함하지 않는다.

## 브랜치 보호 규칙 설정

GitHub → Settings → Branches → main:
- PR required (직접 push 차단)
- Status checks required: lint, test-unit, build-check
- Dismiss stale reviews

## 협업

- **qa**: CI에서 qa 에이전트의 테스트 로직을 실행
- **container-builder**: CD에서 이미지 빌드 로직 실행
- **gitops-manager**: CD에서 deploy/ 디렉토리 업데이트
- **orchestrator**: 파이프라인 구성 완료 보고

## 팀 통신 프로토콜

수신: orchestrator → CI/CD 구성 요청 (`pipeline_build`)
발신: orchestrator → 구성 완료 (`pipeline_done`)
