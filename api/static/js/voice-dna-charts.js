// Voice DNA report — renders the 13 chart_* entries from
// channel_voice_reports.chart_data_json (TZ_CHANNELS.md §7.4) into the
// [data-chart-id] canvases on the page, using Chart.js loaded via CDN.
(function () {
  "use strict";

  var dataEl = document.getElementById("chart-data");
  if (!dataEl || typeof Chart === "undefined") return;

  var chartData;
  try {
    chartData = JSON.parse(dataEl.textContent);
  } catch (e) {
    return;
  }

  var style = getComputedStyle(document.documentElement);
  var palette = [
    style.getPropertyValue("--accent").trim(),
    style.getPropertyValue("--cyan").trim(),
    style.getPropertyValue("--yellow").trim(),
    style.getPropertyValue("--lilac").trim(),
    style.getPropertyValue("--green").trim(),
    style.getPropertyValue("--peach").trim(),
  ];
  var textMuted = style.getPropertyValue("--text-muted").trim();
  var gridColor = style.getPropertyValue("--border").trim();

  Chart.defaults.color = textMuted;
  Chart.defaults.borderColor = gridColor;
  Chart.defaults.font.family = "IBM Plex Sans, sans-serif";

  document.querySelectorAll("[data-chart-id]").forEach(function (canvas) {
    var id = canvas.dataset.chartId;
    var spec = chartData[id];
    if (!spec) return;

    var datasets = (spec.data.datasets || []).map(function (ds, i) {
      var color = palette[i % palette.length];
      return Object.assign(
        {
          backgroundColor: spec.type === "radar" ? color + "33" : color,
          borderColor: color,
        },
        ds
      );
    });
    // A single unlabeled dataset (most of these charts) would otherwise show
    // a legend entry reading literally "undefined".
    var showLegend = datasets.length > 1 || !!(datasets[0] && datasets[0].label);

    new Chart(canvas.getContext("2d"), {
      type: spec.type,
      data: { labels: spec.data.labels, datasets: datasets },
      options: Object.assign(
        {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: showLegend } },
        },
        spec.options || {}
      ),
    });
  });
})();
