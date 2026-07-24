/**
 * 게이지 컴포넌트 — Chart.js Doughnut 기반
 */
export function renderGauge(canvasId, value, label) {
  const ctx = document.getElementById(canvasId)
  if (!ctx) return
  const color = value >= 90 ? '#dc2626' : value >= 80 ? '#d97706' : '#16a34a'
  const chart = Chart.getChart(canvasId)
  if (chart) chart.destroy()
  new Chart(ctx, {
    type: 'doughnut',
    data: {
      // 트랙: 라이트/다크 양쪽에서 자연스러운 반투명 회색
      datasets: [{ data: [value, 100 - value], backgroundColor: [color, 'rgba(128,128,128,0.2)'], borderWidth: 0 }],
    },
    options: {
      cutout: '72%',
      plugins: {
        legend: { display: false },
        tooltip: { enabled: false },
      },
      animation: false,
    },
    plugins: [{
      id: 'centerText',
      afterDraw(chart) {
        const { ctx: c, chartArea: { left, top, width, height } } = chart
        c.save()
        c.font = 'bold 18px sans-serif'
        c.fillStyle = color
        c.textAlign = 'center'
        c.textBaseline = 'middle'
        c.fillText(`${value.toFixed(1)}%`, left + width / 2, top + height / 2)
        c.restore()
      },
    }],
  })
}
