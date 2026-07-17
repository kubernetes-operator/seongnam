# 실제 클러스터 인프라 정보

## 노드 구성

| 노드명 | 역할 | IP | OS | 커널 | SSH 접근 |
|--------|------|----|----|------|---------|
| playcekubectr01 | control-plane | 192.168.77.101 | Ubuntu 24.04.4 | 6.8.0-106-generic | kwlee@192.168.77.101 |
| playcekubectr02 | control-plane | 192.168.77.102 | Ubuntu 24.04.4 | 6.8.0-106-generic | kwlee@192.168.77.102 |
| playcekubectr03 | control-plane | 192.168.77.103 | Ubuntu 24.04.4 | 6.8.0-106-generic | kwlee@192.168.77.103 |
| playcekubewrk01 | worker | 192.168.78.101 | Ubuntu 24.04.4 | 6.8.0-106-generic | kwlee@192.168.78.101 |
| playcekubewrk02 | worker | 192.168.78.102 | Ubuntu 24.04.4 | 6.17.0-22-generic | kwlee@192.168.78.102 |
| playcekubewrk03 | worker | 192.168.78.105 | Ubuntu 24.04.4 | 6.17.0-23-generic | kwlee@192.168.78.105 |
| infra01 | infra (taint 없음) | 192.168.78.103 | Ubuntu 24.04.4 | 6.8.0-107-generic | kwlee@192.168.78.103 |
| infra02 | infra (taint 없음) | 192.168.78.104 | Ubuntu 24.04.4 | 6.8.0-106-generic | kwlee@192.168.78.104 |

- **Kubernetes API**: https://kubernetes:6443
- **K8s 버전**: v1.34.3
- **컨테이너 런타임**: containerd 2.2.1
- **SSH**: 모든 노드에 `kwlee` 계정으로 키 기반 접근 가능
- **kubectl**: 로컬에서 이미 구성됨 (kubeconfig 적용됨)

## 노드 역할 정책

| 역할 | taint | 용도 |
|------|-------|------|
| control-plane | `node-role.kubernetes.io/control-plane:NoSchedule` | K8s 관리 컴포넌트만 |
| worker | 없음 | 일반 애플리케이션 파드 |
| infra | 없음 | Harbor, ArgoCD 등 인프라 서비스 전용 (nodeSelector로 격리) |

infra 노드에 파드 배포 시 nodeSelector:
```yaml
nodeSelector:
  node-role.kubernetes.io/infra: ""
```
(또는 infra 노드에 label이 없으면 worker에 배포)

## 기존 인프라 서비스 (활용 가능)

### Prometheus Stack (monitoring 네임스페이스)
Node Exporter가 **모든 노드에 DaemonSet으로 이미 실행 중**.
OS 메트릭 수집 시 새 DaemonSet 불필요 — Prometheus API 쿼리로 대체.

| 서비스 | 클러스터 내부 DNS | 포트 |
|--------|------------------|------|
| Prometheus | `prometheus-stack-kube-prom-prometheus.monitoring:9090` | 9090 |
| Grafana | `prometheus-stack-grafana.monitoring:80` | 80 |
| Node Exporter | `prometheus-stack-prometheus-node-exporter.monitoring:9100` | 9100 |
| kube-state-metrics | `prometheus-stack-kube-state-metrics.monitoring:8080` | 8080 |
| Alertmanager | `prometheus-stack-kube-prom-alertmanager.monitoring:9093` | 9093 |

### Loki Stack (logging 네임스페이스)
Promtail이 **모든 노드의 컨테이너·시스템 로그를 이미 수집 중**.
위기 분석 시 로그 접근에 별도 에이전트 불필요 — Loki API 쿼리로 대체.

| 서비스 | 클러스터 내부 DNS | 포트 |
|--------|------------------|------|
| Loki | `loki-stack.logging:3100` | 3100 |
| Loki Grafana | `loki-stack-grafana.logging:80` | 80 |

### Gitea (gitea 네임스페이스)
내부 Git 서버. ArgoCD GitOps 저장소로 활용 가능.

| 서비스 | 접근 방법 |
|--------|---------|
| Gitea Web | NodePort 30954 (192.168.78.101:30954 등 워커 IP) |

### Storage
| StorageClass | Provisioner | 기본값 |
|-------------|------------|--------|
| nfs-nas-sc-main | nfs.csi.k8s.io | ✅ 기본값 |
| nfs-nas-sc | nfs.csi.k8s.io | - |

TimescaleDB PVC는 `nfs-nas-sc-main` 사용.

### 기타
- **MetalLB**: LoadBalancer IP 자동 할당
- **nginx-gateway**: Ingress Gateway
- **cert-manager**: TLS 인증서 자동 발급
- **Velero**: 클러스터 백업
- **Headlamp**: 웹 기반 K8s UI

## 미설치 (이번 프로젝트에서 추가)

| 컴포넌트 | 설치 위치 | 목적 |
|---------|---------|------|
| Harbor | infra 노드 (infra01/02) | 컨테이너 이미지 레지스트리 |
| ArgoCD | infra 노드 또는 worker | GitOps 배포 자동화 |
| TimescaleDB | worker (StatefulSet) | 장기 메트릭 저장소 |
| GitHub Actions Runner | worker | CI 빌드 실행 |

## Git / GitHub 정보

- **원격 저장소**: https://github.com/kubernetes-operator/seongnam.git
- **로컬 경로**: /ai/seongnam
- **사용자**: kwlee (blackrusiper@gmail.com)
- **현재 브랜치**: main
- **push 권한**: 자격증명 이미 구성됨 (직접 push 가능)

GitOps 저장소 구조 (동일 repo 내 deploy/ 디렉토리 사용):
```
seongnam/
├── src/              # 소스 코드
├── deploy/           # GitOps 매니페스트 (ArgoCD 감시 경로)
│   ├── base/
│   └── overlays/
│       ├── dev/
│       └── prod/
└── .github/workflows/  # GitHub Actions
```
