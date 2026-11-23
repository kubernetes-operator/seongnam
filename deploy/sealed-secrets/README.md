# Sealed Secrets: os-monitor 시크릿을 GitOps로 관리하기

## 왜 필요한가
`os-monitor-db-secret`(DATABASE_URL, POSTGRES_USER, POSTGRES_PASSWORD)과 `os-monitor-api-secret`(API_KEY)은
그동안 클러스터에 직접 만들어 둔 상태였고 Git에는 없었습니다. 이 상태에서는 다음 문제가 있습니다.
- 클러스터를 다시 만들거나 네임스페이스가 삭제되면 ArgoCD가 복구하지 못합니다.
- 누가 언제 값을 바꿨는지 이력이 남지 않습니다.

Sealed Secrets는 클러스터 안 컨트롤러의 **공개키로 암호화한 `SealedSecret`**만 Git에 커밋합니다.
복호화는 클러스터 안의 개인키로만 할 수 있으므로, 저장소가 공개돼 있어도 안전합니다.

## 절차 (최초 1회)

| 단계 | 누가 | 명령 |
|---|---|---|
| 1. 컨트롤러 설치 | 승인 후 실행 | `helm repo add sealed-secrets https://bitnami.github.io/sealed-secrets`<br>`helm install sealed-secrets sealed-secrets/sealed-secrets -n kube-system --version 2.16.1 -f deploy/sealed-secrets/values.yaml` |
| 2. kubeseal CLI 설치 | 운영자 | https://github.com/bitnami/sealed-secrets/releases 에서 v0.27.1 linux-amd64 를 받아 `/usr/local/bin/kubeseal` 에 둡니다 |
| 3. 봉인 | 운영자 (값이 대화·로그에 남지 않도록) | `scripts/seal-secrets.sh` |
| 4. 확인 | 누구나 | `kubectl kustomize deploy/overlays/prod \| grep -c 'kind: SealedSecret'` → 2 |
| 5. 커밋·푸시 | 승인 후 | `deploy/base/secrets/`, `deploy/base/kustomization.yaml` |

푸시하면 ArgoCD가 `SealedSecret`을 동기화하고, 컨트롤러가 같은 이름의 `Secret`을 관리하게 됩니다.
스크립트가 기존 Secret에 `sealedsecrets.bitnami.com/managed=true`를 붙이므로 **값은 바뀌지 않고 다운타임도 없습니다.**

## 꼭 지킬 것
- **개인키 백업:** 컨트롤러를 다시 설치하면 키가 새로 만들어지고, 기존 SealedSecret을 풀 수 없게 됩니다.
  `kubectl -n kube-system get secret -l sealedsecrets.bitnami.com/sealed-secrets-key -o yaml > <안전한 오프라인 위치>`
  로 백업하고, **이 파일은 절대 Git에 올리지 마세요.**
- **값 변경:** Secret을 바꾼 뒤(`kubectl edit`/`create --dry-run | apply`) `scripts/seal-secrets.sh`를 다시 실행하고 커밋합니다.
  SealedSecret만 바꾸고 푸시해도 됩니다. Git이 진실 소스이므로, 클러스터에서 직접 고친 값은 다음 동기화 때 Git 값으로 되돌아갑니다.
- 봉인 결과는 **네임스페이스와 이름에 묶여 있습니다**(strict scope). 다른 이름이나 네임스페이스로 복사하면 복호화되지 않습니다.
