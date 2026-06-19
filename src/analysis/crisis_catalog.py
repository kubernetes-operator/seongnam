"""위기 유형 카탈로그 — 7가지 위기 유형별 진단 절차·즉각 조치·공식 문서 링크."""

CRISIS_CATALOG = {
    "HIGH_CPU": {
        "description": "CPU 사용률이 임계값(90%)을 초과했습니다.",
        "diagnosis_steps": [
            "kubectl top pods --all-namespaces --sort-by=cpu | head -15",
            "ssh kwlee@<node-ip> 'top -b -n1 | head -20'",
            "ssh kwlee@<node-ip> 'ps aux --sort=-%cpu | head -15'",
        ],
        "immediate_actions": [
            "kubectl top pods --all-namespaces | sort -k3 -rn | head -10  # 고사용 파드 확인",
            "kubectl set resources deployment <name> --limits cpu=500m -n <ns>  # CPU limit 설정",
            "kubectl autoscale deployment <name> --cpu-percent=70 --min=2 --max=10  # HPA 설정",
        ],
        "references": [
            {"title": "Kubernetes CPU 리소스 관리", "url": "https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/"},
            {"title": "Linux CPU 성능 분석 (Brendan Gregg)", "url": "https://www.brendangregg.com/linuxperf.html"},
        ],
    },
    "MEMORY_EXHAUSTION": {
        "description": "메모리 사용률이 임계값(90%)을 초과했습니다. OOM Killer 활성화 위험.",
        "log_patterns": ["Out of memory: Kill process", "oom-kill", "Memory cgroup out of memory"],
        "diagnosis_steps": [
            "ssh kwlee@<node-ip> 'free -h && cat /proc/meminfo | grep -E \"MemTotal|MemAvailable\"'",
            "ssh kwlee@<node-ip> 'ps aux --sort=-%mem | head -15'",
            "kubectl get events --all-namespaces | grep OOM",
        ],
        "immediate_actions": [
            "ssh kwlee@<node-ip> 'sync && echo 1 > /proc/sys/vm/drop_caches'  # 페이지 캐시 해제",
            "kubectl rollout restart deployment <name> -n <ns>  # 메모리 누수 프로세스 재시작",
            "kubectl drain <node> --ignore-daemonsets  # 긴급 시 파드 다른 노드로 이동",
        ],
        "references": [
            {"title": "Linux Kernel OOM Killer", "url": "https://www.kernel.org/doc/html/latest/admin-guide/mm/concepts.html"},
            {"title": "Kubernetes 메모리 리소스 관리", "url": "https://kubernetes.io/docs/tasks/configure-pod-container/assign-memory-resource/"},
        ],
    },
    "DISK_FULL": {
        "description": "디스크 사용률이 임계값(90%)을 초과했습니다.",
        "log_patterns": ["No space left on device", "ENOSPC", "write failed"],
        "diagnosis_steps": [
            "ssh kwlee@<node-ip> 'df -h && du -sh /var/log/* 2>/dev/null | sort -hr | head -10'",
            "ssh kwlee@<node-ip> 'du -sh /var/lib/containerd/* 2>/dev/null | sort -hr | head -5'",
            "kubectl get events | grep -i evict",
        ],
        "immediate_actions": [
            "ssh kwlee@<node-ip> 'journalctl --vacuum-size=500M'  # 오래된 로그 삭제",
            "ssh kwlee@<node-ip> 'crictl rmi --prune'  # 미사용 컨테이너 이미지 삭제",
            "kubectl delete pod --field-selector=status.phase=Failed --all-namespaces",
        ],
        "references": [
            {"title": "K8s 노드 디스크 압력 관리", "url": "https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/"},
            {"title": "containerd 이미지 관리", "url": "https://github.com/containerd/containerd/blob/main/docs/ops.md"},
        ],
    },
    "HIGH_LOAD": {
        "description": "Load Average가 CPU 코어 수 대비 임계값(2.0배)을 초과했습니다.",
        "diagnosis_steps": [
            "ssh kwlee@<node-ip> 'uptime && iostat -x 1 3'",
            "ssh kwlee@<node-ip> 'ps aux --sort=-pcpu | head -15'",
            "ssh kwlee@<node-ip> 'dmesg | grep -i \"hung task\\|soft lockup\" | tail -10'",
        ],
        "immediate_actions": [
            "I/O 대기 확인: ssh kwlee@<node-ip> 'iostat -x 1 5 | grep -v ^$'",
            "스케줄링 병목: kubectl describe node <node> | grep -A5 Conditions",
            "kubectl cordon <node>  # 신규 파드 스케줄링 차단 (점검 중)",
        ],
        "references": [
            {"title": "Linux Load Average 이해", "url": "https://www.brendangregg.com/blog/2017-08-08/linux-load-averages.html"},
            {"title": "K8s 노드 관리", "url": "https://kubernetes.io/docs/concepts/architecture/nodes/"},
        ],
    },
    "CRASHLOOP_BACKOFF": {
        "description": "파드가 CrashLoopBackOff 상태입니다.",
        "diagnosis_steps": [
            "kubectl logs <pod> --previous -n <namespace>  # 이전 컨테이너 로그",
            "kubectl describe pod <pod> -n <namespace>",
            "kubectl get events -n <namespace> --field-selector involvedObject.name=<pod>",
        ],
        "immediate_actions": [
            "이전 로그에서 오류 원인 확인 후 설정 수정",
            "ConfigMap/Secret 값 검증: kubectl get configmap <name> -o yaml -n <ns>",
            "리소스 부족 확인: kubectl top pod <pod> -n <namespace>",
        ],
        "references": [
            {"title": "K8s 파드 라이프사이클", "url": "https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/"},
            {"title": "K8s 파드 디버깅", "url": "https://kubernetes.io/docs/tasks/debug/debug-application/debug-running-pod/"},
        ],
    },
    "NODE_NOT_READY": {
        "description": "노드가 NotReady 상태입니다.",
        "diagnosis_steps": [
            "kubectl describe node <node-name>",
            "ssh kwlee@<node-ip> 'systemctl status kubelet'",
            "ssh kwlee@<node-ip> 'journalctl -u kubelet --since \"10 min ago\" | tail -50'",
        ],
        "immediate_actions": [
            "ssh kwlee@<node-ip> 'systemctl restart kubelet'",
            "디스크 압력 확인: ssh kwlee@<node-ip> 'df -h'",
            "네트워크 확인: ssh kwlee@<node-ip> 'ping -c3 kubernetes'",
        ],
        "references": [
            {"title": "K8s 노드 문제 해결", "url": "https://kubernetes.io/docs/tasks/debug/debug-cluster/"},
            {"title": "kubelet 설정 가이드", "url": "https://kubernetes.io/docs/reference/config-api/kubelet-config.v1beta1/"},
        ],
    },
    "OOM_KILLED": {
        "description": "컨테이너가 OOMKilled로 강제 종료됐습니다.",
        "diagnosis_steps": [
            "kubectl describe pod <pod> -n <namespace> | grep -A5 'Last State'",
            "ssh kwlee@<node-ip> 'dmesg | grep -i oom | tail -20'",
        ],
        "immediate_actions": [
            "memory limit 1.5배 이상 증가: kubectl set resources deployment <name> --limits memory=2Gi -n <ns>",
            "VPA 적용 검토 (자동 리소스 조정)",
            "메모리 누수 여부 확인: kubectl top pod <pod> -n <ns> --containers",
        ],
        "references": [
            {"title": "K8s OOMKilled 해결", "url": "https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/"},
            {"title": "VPA (Vertical Pod Autoscaler)", "url": "https://github.com/kubernetes/autoscaler/tree/master/vertical-pod-autoscaler"},
        ],
    },
}
