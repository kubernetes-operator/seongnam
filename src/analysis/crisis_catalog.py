"""위기 유형 카탈로그 — 4가지 위기 유형별 진단 절차·즉각 조치·공식 문서 링크."""

CRISIS_CATALOG = {
    "HIGH_CPU": {
        "description": "CPU 사용률이 임계값(90%)을 초과했습니다.",
        "diagnosis_steps": [
            "ssh kwlee@<node-ip> 'top -b -n1 | head -20'",
            "ssh kwlee@<node-ip> 'ps aux --sort=-%cpu | head -15'",
        ],
        "immediate_actions": [],
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
        ],
        "immediate_actions": [
            "ssh kwlee@<node-ip> 'sync && echo 1 > /proc/sys/vm/drop_caches'  # 페이지 캐시 해제",
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
        ],
        "immediate_actions": [
            "ssh kwlee@<node-ip> 'journalctl --vacuum-size=500M'  # 오래된 로그 삭제",
            "ssh kwlee@<node-ip> 'crictl rmi --prune'  # 미사용 컨테이너 이미지 삭제",
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
        ],
        "references": [
            {"title": "Linux Load Average 이해", "url": "https://www.brendangregg.com/blog/2017-08-08/linux-load-averages.html"},
            {"title": "K8s 노드 관리", "url": "https://kubernetes.io/docs/concepts/architecture/nodes/"},
        ],
    },
}
