/**
 * 게이지 컴포넌트 — Chart.js Doughnut 기반
 */
export function renderGauge(canvasId, value, label) {
  const ctx = document.getElementById(canvasId)
  if (!ctx) return
  const color = value >= 90 ? '#dc3545' : value >= 80 ? '#ffc107' : '#198754'
  const chart = Chart.getChart(canvasId)
  if (chart) chart.destroy()
  new Chart(ctx, {
    type: 'doughnut',
    data: {
      datasets: [{ data: [value, 100 - value], backgroundColor: [color, '#e9ecef'], borderWidth: 0 }],
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
