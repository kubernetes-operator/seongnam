#!/bin/bash
set -euo pipefail

# 저장소 루트에서 실행: bash scripts/build-push-images.sh
# registry.local.cloud로 resolve되지 않으면 --add-host 로 hostAlias와 동일하게 지정하거나
# /etc/hosts 에 "192.168.77.100 registry.local.cloud" 추가 필요.

REGISTRY="registry.local.cloud:5000"
PROJECT="os-monitor"
SHA="$(git rev-parse --short HEAD)"

echo "== Build & push tag: ${SHA} (+ latest) =="

for component in api collector dashboard; do
  image="${REGISTRY}/${PROJECT}/${component}"
  echo "--- ${component} ---"
  docker build -f "Dockerfile.${component}" -t "${image}:${SHA}" -t "${image}:latest" .
  docker push "${image}:${SHA}"
  docker push "${image}:latest"
done

echo "== Done. 배포된 파드는 이미지가 준비되면 자동으로 정상화됩니다 (재적용 불필요) =="
