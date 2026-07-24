# ArgoCD 배포/노출 구성

이 디렉토리는 클러스터에 설치된 ArgoCD 와 그 외부 노출(Gateway API) 구성을 담는다.

## 구성 요소

| 파일 | 역할 |
|------|------|
| `application-prod.yaml` | os-monitor 앱을 배포하는 ArgoCD Application (repo `kubernetes-operator/seongnam`, path `deploy/overlays/prod`, auto-sync+selfHeal+prune) |
| `argocd-cmd-params-cm.yaml` | argocd-server 파라미터 (insecure + 서브패스 rootpath) |
| `proxy.yaml` | 서브패스 노출용 nginx 리버스 프록시 (base href 재작성) |
| `httproute.yaml` | `test2.studiobasa.com/argocd` → `argocd-proxy` Gateway API 라우트 |

## 외부 노출: `https://test2.studiobasa.com/argocd/`

경로 기반 노출(다른 앱들과 동일하게 `test2.studiobasa.com` 공유). 흐름:

```
브라우저 → NGINX Gateway Fabric(gateway/default, 192.168.77.200, letsencrypt TLS)
        → HTTPRoute(argocd-route, PathPrefix /argocd)
        → Service argocd-proxy(nginx)          # <base href="/"> → <base href="/argocd/"> 재작성
        → Service argocd-server(:80, insecure, rootpath=/argocd)
```

### 왜 프록시가 필요한가
ArgoCD v3.4.5 는 `server.rootpath=/argocd` 설정 시 **자산/API 는 `/argocd/` 아래로 정상 서빙**하지만
`index.html` 의 `<base href="/">` 를 `/argocd/` 로 **재작성하지 않는다**. 그대로 두면 브라우저가
자산을 사이트 루트(`/main.js`)에서 찾게 되고, 루트는 다른 앱이 점유하고 있어 UI 가 깨진다.
`argocd-proxy` 의 nginx `sub_filter` 가 그 한 줄만 교정한다.

## 설치/재적용 순서

```bash
# 1) ArgoCD 설치 (대형 CRD 때문에 server-side apply)
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml --server-side --force-conflicts

# 2) 서브패스 파라미터 적용 후 서버 재시작
kubectl apply -f deploy/argocd/argocd-cmd-params-cm.yaml
kubectl rollout restart deploy/argocd-server -n argocd

# 3) 프록시 + 라우트
kubectl apply -f deploy/argocd/proxy.yaml
kubectl apply -f deploy/argocd/httproute.yaml

# 4) Application
kubectl apply -f deploy/argocd/application-prod.yaml
```

초기 admin 비밀번호:
```bash
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d
```
