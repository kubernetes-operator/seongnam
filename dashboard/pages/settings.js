import { API } from '../api.js'

export async function renderSettings() {
  const main = document.getElementById('main-content')
  const me = await API.auth.me().catch(() => null)
  const username = me?.data?.username || ''

  main.innerHTML = `
    <h2>설정</h2>
    <div class="card" style="max-width:480px;margin-bottom:20px">
      <div class="card-title">현재 계정</div>
      <div style="font-size:16px">👤 ${username || '(알 수 없음)'}</div>
    </div>

    <div class="card" style="max-width:480px">
      <div class="card-title">비밀번호 변경</div>
      <form id="pw-form" style="display:flex;flex-direction:column;gap:12px;margin-top:8px">
        <div class="field">
          <label class="muted">현재 비밀번호</label>
          <input type="password" id="cur-pw" autocomplete="current-password" required>
        </div>
        <div class="field">
          <label class="muted">새 비밀번호 (8자 이상)</label>
          <input type="password" id="new-pw" autocomplete="new-password" minlength="8" required>
        </div>
        <div class="field">
          <label class="muted">새 비밀번호 확인</label>
          <input type="password" id="new-pw2" autocomplete="new-password" minlength="8" required>
        </div>
        <div id="pw-msg" style="font-size:13px;min-height:18px"></div>
        <div><button type="submit" class="btn-primary btn-sm">비밀번호 변경</button></div>
      </form>
    </div>
  `

  document.getElementById('pw-form').addEventListener('submit', async (e) => {
    e.preventDefault()
    const msg = document.getElementById('pw-msg')
    const cur = document.getElementById('cur-pw').value
    const n1 = document.getElementById('new-pw').value
    const n2 = document.getElementById('new-pw2').value
    if (n1 !== n2) { msg.className = 'text-critical'; msg.textContent = '새 비밀번호가 일치하지 않습니다.'; return }
    try {
      await API.auth.changePassword(cur, n1)
      msg.className = 'text-ok'
      msg.textContent = '✅ 변경되었습니다. 보안을 위해 다시 로그인해 주세요.'
      // 비밀번호 변경 시 서버가 모든 세션을 무효화하므로 로그아웃 처리
      setTimeout(() => { localStorage.removeItem('session_token'); location.reload() }, 1500)
    } catch (err) {
      msg.className = 'text-critical'
      msg.textContent = '실패: ' + err.message
    }
  })
}
