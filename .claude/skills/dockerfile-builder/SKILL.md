---
name: dockerfile-builder
description: |
  컴포넌트별 최적화된 multi-stage Dockerfile을 작성하고, Harbor 레지스트리 이미지 빌드·푸시 스크립트를 생성하는 스킬. 'Dockerfile 작성', '컨테이너 이미지 빌드', 'Harbor 푸시', 'multi-stage 빌드', '컨테이너화', 'Docker 이미지 최적화', '.dockerignore 생성', 'trivy 보안 스캔', 'Harbor 설치' 등 컨테이너 이미지 관련 요청 시 반드시 이 스킬을 사용할 것.
---

# Dockerfile Builder 스킬

## 이미지 구성

| 컴포넌트 | Base | 특이사항 |
|---------|------|---------|
| API 서버 | python:3.11-slim | uvicorn workers: 2 |
| 수집기 | python:3.11-slim | openssh-client 필요 (asyncssh) |
| 대시보드 | nginx:1.25-alpine | 정적 파일만, entrypoint.sh로 API URL 주입 |

---

## Dockerfile.api

```dockerfile
# Stage 1: 의존성 빌드
FROM python:3.11-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: 실행 이미지
FROM python:3.11-slim AS runtime
WORKDIR /app

RUN groupadd -r appuser && useradd -r -g appuser appuser

COPY --from=builder /install /usr/local
COPY src/api/ ./api/
COPY src/db/ ./db/

USER appuser
EXPOSE 8000

# exec form — SIGTERM이 uvicorn으로 직접 전달됨
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

---

## Dockerfile.collector

```dockerfile
FROM python:3.11-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.11-slim AS runtime
WORKDIR /app

# asyncssh가 내부적으로 OpenSSH 클라이언트를 사용
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r appuser && useradd -r -g appuser appuser

COPY --from=builder /install /usr/local
COPY src/collector/ ./collector/
COPY src/analysis/ ./analysis/
COPY src/db/ ./db/

# SSH 키는 K8s Secret으로 마운트됨 → /app/.ssh/id_rsa
# 절대 이미지에 포함하지 않는다

USER appuser
CMD ["python", "-m", "collector.os_service"]
```

---

## Dockerfile.dashboard

```dockerfile
FROM nginx:1.25-alpine AS runtime

COPY dashboard/ /usr/share/nginx/html/
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY deploy/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 80
ENTRYPOINT ["/entrypoint.sh"]
```

```sh
# deploy/entrypoint.sh
#!/bin/sh
# K8s ConfigMap으로 주입된 환경변수를 env.js에 기록
# API_BASE_URL과 API_KEY는 Deployment의 env 블록에서 주입
cat > /usr/share/nginx/html/env.js << ENVEOF
window.ENV_API_URL = '${API_BASE_URL:-http://k8s-monitor-api:8000}';
ENVEOF
exec nginx -g 'daemon off;'
```

```nginx
# deploy/nginx.conf
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    # SPA: 존재하지 않는 경로는 index.html로 폴백
    location / {
        try_files $uri $uri/ /index.html;
    }

    # 정적 자산 캐시
    location ~* \.(js|css|png|jpg|gif|ico|svg)$ {
        expires 7d;
        add_header Cache-Control "public, no-transform";
    }
}
```

---

## .dockerignore

```
.git/
.github/
tests/
*.md
deploy/
__pycache__/
*.pyc
.env*
*.log
_workspace/
```

---

## 이미지 태깅 전략

```
harbor.<domain>/k8s-monitor/api:abc1234     # git SHA (8자) — 배포 커밋 역추적
harbor.<domain>/k8s-monitor/api:latest      # main 브랜치 최신
```

git SHA를 태그로 쓰면 `kubectl get deployment -o jsonpath=...`로 배포된 커밋을 즉시 확인할 수 있다.

---

## 빌드 & 푸시 스크립트

```bash
#!/bin/bash
# scripts/build-push.sh
set -euo pipefail

REGISTRY=${HARBOR_REGISTRY}    # GitHub Secret에서 주입
PROJECT="k8s-monitor"
GIT_SHA=$(git rev-parse --short HEAD)

declare -A DOCKERFILES=(
  ["api"]="Dockerfile.api"
  ["collector"]="Dockerfile.collector"
  ["dashboard"]="Dockerfile.dashboard"
)

for comp in "${!DOCKERFILES[@]}"; do
  df="${DOCKERFILES[$comp]}"
  image="${REGISTRY}/${PROJECT}/${comp}"

  docker build -f "${df}" \
    -t "${image}:${GIT_SHA}" \
    -t "${image}:latest" .

  # HIGH/CRITICAL 취약점 있으면 중단
  trivy image --exit-code 1 --severity HIGH,CRITICAL "${image}:${GIT_SHA}"

  docker push "${image}:${GIT_SHA}"
  docker push "${image}:latest"
  echo "✓ ${image}:${GIT_SHA}"
done

echo "BUILD_SHA=${GIT_SHA}" >> "${GITHUB_OUTPUT:-/dev/null}"
```

---

## Harbor 설치 (infra 노드)

```bash
helm repo add harbor https://helm.goharbor.io
helm install harbor harbor/harbor \
  --namespace harbor --create-namespace \
  --set expose.type=loadBalancer \
  --set persistence.persistentVolumeClaim.registry.storageClass=nfs-nas-sc-main \
  --set nodeSelector."node-role\.kubernetes\.io/infra"=""
```

Harbor 설치 후 외부 주소를 확인하여 `HARBOR_REGISTRY` GitHub Secret에 등록한다.

---

## 보안 원칙

1. **non-root**: 모든 컨테이너는 `appuser`로 실행
2. **SSH 키 분리**: 이미지에 절대 포함 금지 — K8s Secret으로 마운트
3. **secrets 분리**: .env 파일, API 키는 이미지 빌드에서 완전 제외 (.dockerignore)
4. **trivy 스캔**: HIGH/CRITICAL 취약점 발견 시 Harbor 푸시 차단
5. **multi-stage**: builder 스테이지의 pip, 빌드 도구는 최종 이미지에 미포함
