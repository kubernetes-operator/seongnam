---
name: argocd-gitops
description: |
  ArgoCD를 Kubernetes 클러스터에 설치하고, Kustomize 기반 GitOps 저장소 구조를 설계하며, ArgoCD Application CR을 생성하는 스킬. 'ArgoCD 설치', 'GitOps 구성', 'Kustomize 오버레이', 'deploy 디렉토리 구성', '자동 배포 설정', 'ArgoCD Application 생성', 'GitOps 저장소 구조', '이미지 태그 kustomize 업데이트', '롤백 설정', 'selfHeal 설정' 등 GitOps·배포 자동화 관련 요청 시 반드시 이 스킬을 사용할 것.
---

# ArgoCD GitOps 스킬

## GitOps 저장소 구조

동일 저장소(`github.com/kubernetes-operator/seongnam`)의 `deploy/` 디렉토리를 ArgoCD가 감시한다.

```
seongnam/
└── deploy/
    ├── base/                          # 공통 K8s 매니페스트
    │   ├── kustomization.yaml
    │   ├── namespace.yaml
    │   ├── timescaledb/
    │   │   ├── statefulset.yaml
    │   │   ├── service.yaml
    │   │   └── pvc.yaml
    │   ├── api/
    │   │   ├── deployment.yaml
    │   │   ├── service.yaml
    │   │   └── hpa.yaml
    │   ├── collector/
    │   │   ├── deployment.yaml
    │   │   └── rbac.yaml
    │   ├── dashboard/
    │   │   ├── deployment.yaml
    │   │   └── service.yaml
    │   └── cronjobs/
    │       ├── report-daily.yaml
    │       ├── report-weekly.yaml
    │       ├── report-monthly.yaml
    │       └── report-yearly.yaml
    ├── overlays/
    │   ├── dev/
    │   │   ├── kustomization.yaml
    │   │   └── patch-replicas-dev.yaml
    │   └── prod/
    │       ├── kustomization.yaml     # CD에서 이미지 태그 자동 업데이트
    │       └── patch-replicas-prod.yaml
    └── argocd/
        └── application-prod.yaml
```

---

## ArgoCD 설치

```bash
kubectl create namespace argocd
kubectl apply -n argocd \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# infra 노드에 스케줄링
kubectl patch deployment argocd-server -n argocd -p '{
  "spec": {"template": {"spec": {
    "nodeSelector": {"node-role.kubernetes.io/infra": ""}
  }}}
}'

# 초기 admin 비밀번호 확인
kubectl get secret argocd-initial-admin-secret -n argocd \
  -o jsonpath='{.data.password}' | base64 -d
```

---

## ArgoCD Application CR

```yaml
# deploy/argocd/application-prod.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: k8s-monitor-prod
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/kubernetes-operator/seongnam.git
    targetRevision: main
    path: deploy/overlays/prod
  destination:
    server: https://kubernetes.default.svc
    namespace: k8s-monitor
  syncPolicy:
    automated:
      prune: true       # 삭제된 리소스 자동 제거
      selfHeal: true    # 드리프트 감지 시 자동 복구
    syncOptions:
      - CreateNamespace=true
      - PrunePropagationPolicy=foreground
    retry:
      limit: 3
      backoff:
        duration: 30s
        factor: 2
        maxDuration: 5m
```

---

## Kustomize 구성

### base/kustomization.yaml

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: k8s-monitor

resources:
  - namespace.yaml
  - timescaledb/statefulset.yaml
  - timescaledb/service.yaml
  - api/deployment.yaml
  - api/service.yaml
  - api/hpa.yaml
  - collector/deployment.yaml
  - collector/rbac.yaml
  - dashboard/deployment.yaml
  - dashboard/service.yaml
  - cronjobs/report-daily.yaml
  - cronjobs/report-weekly.yaml
  - cronjobs/report-monthly.yaml
  - cronjobs/report-yearly.yaml

commonLabels:
  app.kubernetes.io/part-of: k8s-monitor
  app.kubernetes.io/managed-by: argocd
```

### overlays/prod/kustomization.yaml

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - ../../base

# CD 워크플로우에서 git SHA로 자동 업데이트됨
images:
  - name: k8s-monitor/api
    newName: harbor.<domain>/k8s-monitor/api
    newTag: abc1234
  - name: k8s-monitor/collector
    newName: harbor.<domain>/k8s-monitor/collector
    newTag: abc1234
  - name: k8s-monitor/dashboard
    newName: harbor.<domain>/k8s-monitor/dashboard
    newTag: abc1234

patches:
  - path: patch-replicas-prod.yaml
```

### overlays/prod/patch-replicas-prod.yaml

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: k8s-monitor-api
spec:
  replicas: 2
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: k8s-monitor-dashboard
spec:
  replicas: 2
```

### overlays/dev/kustomization.yaml

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: k8s-monitor-dev

resources:
  - ../../base

images:
  - name: k8s-monitor/api
    newName: harbor.<domain>/k8s-monitor/api
    newTag: latest

patches:
  - path: patch-replicas-dev.yaml
```

---

## Harbor imagePullSecret 생성

```bash
# 코드에 포함하지 않고 kubectl로 직접 생성
kubectl create secret docker-registry harbor-registry-secret \
  --docker-server=harbor.<domain> \
  --docker-username=<user> \
  --docker-password=<pass> \
  -n k8s-monitor
```

각 Deployment의 `spec.template.spec`에 참조:

```yaml
imagePullSecrets:
  - name: harbor-registry-secret
```

---

## 배포 확인

```bash
# ArgoCD 동기화 상태
kubectl get applications -n argocd

# 현재 배포된 이미지 태그 (어느 커밋이 배포되어 있는지)
kubectl get deployment k8s-monitor-api -n k8s-monitor \
  -o jsonpath='{.spec.template.spec.containers[0].image}'

# ArgoCD CLI
argocd app sync k8s-monitor-prod
argocd app status k8s-monitor-prod
```

---

## 롤백 전략

```bash
# 방법 1: Git 리버트 → CI/CD 자동 재배포 (권장)
git revert HEAD && git push origin main

# 방법 2: ArgoCD CLI로 특정 revision으로 롤백
argocd app rollback k8s-monitor-prod <revision-id>
```

---

## 핵심 원칙

1. **단일 진실 소스**: `deploy/` 디렉토리만이 클러스터 상태를 정의. `kubectl apply` 직접 사용 금지.
2. **이미지 태그 = git SHA**: 태그로 배포된 커밋을 즉시 역추적 가능.
3. **자격증명 분리**: imagePullSecret·DB 접속 정보는 K8s Secret으로만 관리.
4. **자동 복구**: `selfHeal: true`로 수동 변경(드리프트)을 자동 원복.
