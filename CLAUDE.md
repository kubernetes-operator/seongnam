# CLAUDE.md

## 하네스: K8s OS Monitor

**목표:** Kubernetes 클러스터의 Base OS 및 K8s 상태를 수집·저장·분석·예측·시각화하는 통합 모니터링 플랫폼

**트리거:** K8s 모니터링, OS 수집, 리포트 생성, 위기 감지, 예측 분석, 대시보드 구축, CLI 구현, QA 검증, 컨테이너 빌드, CI/CD 파이프라인, GitOps 배포 등 모니터링 시스템 관련 작업 요청 시 `k8s-os-monitor` 스킬을 사용하라. 단순 개념 질문은 직접 응답 가능.

**변경 이력:**
| 날짜 | 변경 내용 | 대상 | 사유 |
|------|----------|------|------|
| 2026-06-20 | 초기 하네스 구성 | 전체 | K8s OS 모니터링 시스템 하네스 신규 구축 |
| 2026-06-20 | CI/CD 에이전트 4개 추가 | qa, container-builder, cicd-pipeline, gitops-manager | GitHub Actions + Harbor + ArgoCD GitOps 파이프라인 구성 |
| 2026-06-20 | 스킬 4개 추가 | qa-testing, dockerfile-builder, github-actions, argocd-gitops | CI/CD 파이프라인 스킬 완성 |
| 2026-06-20 | 오케스트레이터 Phase 9-12 추가 | k8s-os-monitor/SKILL.md | QA·컨테이너·CI/CD·GitOps Phase 추가 |
