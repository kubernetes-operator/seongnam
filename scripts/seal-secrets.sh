#!/usr/bin/env bash
# os-monitor 네임스페이스의 기존 Secret 을 SealedSecret 으로 변환해 deploy/base/secrets/ 에 저장한다.
# - 평문 값은 화면·파일·셸 히스토리 어디에도 출력하지 않는다 (kubectl → kubeseal 파이프로만 전달).
# - 결과 파일은 클러스터 컨트롤러 공개키로 암호화되어 Git 커밋이 안전하다.
# 선행 조건: sealed-secrets 컨트롤러 설치(deploy/sealed-secrets/README.md), kubeseal CLI 설치.
set -euo pipefail

NS=os-monitor
SECRETS=(os-monitor-db-secret os-monitor-api-secret)
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/deploy/base/secrets"
mkdir -p "$OUT"

command -v kubeseal >/dev/null || { echo "kubeseal 이 필요합니다"; exit 1; }

for s in "${SECRETS[@]}"; do
  # 메타데이터(소유자·버전 등)는 제거하고 이름·네임스페이스·데이터만 봉인
  kubectl -n "$NS" get secret "$s" -o json \
    | python3 -c 'import json,sys
d=json.load(sys.stdin)
print(json.dumps({"apiVersion":"v1","kind":"Secret","type":d.get("type","Opaque"),
  "metadata":{"name":d["metadata"]["name"],"namespace":d["metadata"]["namespace"]},
  "data":d["data"]}))' \
    | kubeseal --controller-namespace kube-system --controller-name sealed-secrets-controller \
               --format yaml > "$OUT/$s.sealed.yaml"
  echo "봉인 완료: deploy/base/secrets/$s.sealed.yaml"

  # 기존(수동 생성) Secret 을 컨트롤러가 관리하도록 표시 — 없으면 컨트롤러가 덮어쓰기를 거부한다
  kubectl -n "$NS" annotate secret "$s" sealedsecrets.bitnami.com/managed="true" --overwrite >/dev/null
done

cat > "$OUT/kustomization.yaml" <<KEOF
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
$(for s in "${SECRETS[@]}"; do echo "  - $s.sealed.yaml"; done)
KEOF

grep -q 'secrets' "$ROOT/deploy/base/kustomization.yaml" \
  || sed -i 's#^resources:#resources:\n  - secrets#' "$ROOT/deploy/base/kustomization.yaml"

echo "완료. 확인: kubectl kustomize deploy/overlays/prod | grep -c 'kind: SealedSecret'  (기대값 2)"
