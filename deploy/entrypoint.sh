#!/bin/sh
# API_BASE_URL 환경변수를 app.js에 주입하고 nginx 실행
API_BASE="${API_BASE_URL:-}"

# index.html 의 window.API_BASE_URL 플레이스홀더를 실제 값으로 치환
sed -i "s|window.API_BASE_URL = ''|window.API_BASE_URL = '${API_BASE}'|g" \
    /usr/share/nginx/html/index.html 2>/dev/null || true

exec nginx -g "daemon off;"
