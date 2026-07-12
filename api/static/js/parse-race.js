// Channel Parser step 2 — polls job status and drives a small canvas
// animation while the user waits (TZ_CHANNELS.md §3.3). Vanilla JS, no
// external libraries. Speed is tied to the real progress_pct from the API,
// not to clicks — clicking/Space only gives a 0.5s cosmetic boost.
(function () {
  "use strict";

  var card = document.getElementById("parse-progress-card");
  if (!card) return;

  var jobId = card.dataset.jobId;
  var statusLine = document.getElementById("parse-status-line");
  var progressFill = document.getElementById("parse-progress-fill");
  var progressText = document.getElementById("parse-progress-text");
  var doneActions = document.getElementById("parse-done-actions");
  var doneCount = document.getElementById("parse-done-count");
  var failedActions = document.getElementById("parse-failed-actions");
  var errorText = document.getElementById("parse-error-text");
  var canvas = document.getElementById("parse-race-canvas");
  var ctx = canvas ? canvas.getContext("2d") : null;

  var STATUS_LABELS = {
    pending: "Queued…",
    validating: "Checking the channel exists…",
    scraping: "Fetching posts…",
    storing: "Saving results…",
    analyzing: "Running Voice DNA analysis…",
    done: "Done!",
    failed: "Failed.",
  };

  var state = {
    progressPct: parseFloat(card.dataset.initialCurrent) && parseFloat(card.dataset.initialTotal)
      ? (parseFloat(card.dataset.initialCurrent) / parseFloat(card.dataset.initialTotal)) * 100
      : 0,
    status: card.dataset.initialStatus || "pending",
    finished: false,
    boostUntil: 0,
  };

  var obstacles = [];
  var lastObstacleAt = 0;
  var roadOffset = 0;

  function updateUI(data) {
    state.status = data.status;
    state.progressPct = data.progress_pct;

    statusLine.textContent = STATUS_LABELS[data.status] || data.status;
    progressFill.style.width = Math.max(0, Math.min(100, data.progress_pct)) + "%";
    progressText.textContent = data.progress_current + " / " + (data.progress_total || "?") + " posts";

    if (data.status === "done") {
      state.finished = true;
      doneCount.textContent = data.posts_count;
      doneActions.style.display = "block";
    } else if (data.status === "failed") {
      state.finished = true;
      errorText.textContent = data.error_message || "Unknown error.";
      failedActions.style.display = "block";
    }
  }

  function poll() {
    if (state.finished) return;
    fetch("/api/channels/parse/" + jobId + "/status")
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        updateUI(data);
        if (!state.finished) {
          setTimeout(poll, 2000);
        }
      })
      .catch(function () {
        setTimeout(poll, 2000);
      });
  }

  // --- Mini-game (visual only, no win/lose condition) ---

  function boost() {
    state.boostUntil = performance.now() + 500;
  }

  window.addEventListener("keydown", function (e) {
    if (e.code === "Space") {
      e.preventDefault();
      boost();
    }
  });
  if (canvas) {
    canvas.addEventListener("click", boost);
  }

  function drawRoad(width, height, dt) {
    roadOffset = (roadOffset + dt * 0.08) % 40;
    ctx.strokeStyle = "rgba(244, 242, 236, 0.15)";
    ctx.lineWidth = 2;
    ctx.setLineDash([16, 12]);
    ctx.lineDashOffset = -roadOffset;
    ctx.beginPath();
    ctx.moveTo(0, height - 30);
    ctx.lineTo(width, height - 30);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  function drawShip(x, y) {
    ctx.save();
    ctx.translate(x, y);
    ctx.fillStyle = "#ff5c45"; // --accent
    ctx.beginPath();
    ctx.moveTo(18, 0);
    ctx.lineTo(-14, -9);
    ctx.lineTo(-14, 9);
    ctx.closePath();
    ctx.fill();
    ctx.fillRect(-20, -6, 8, 12);
    ctx.restore();
  }

  function spawnObstacle(width) {
    var emoji = Math.random() < 0.5 ? "🐢" : "📎";
    obstacles.push({ x: width + 20, y: 40 + Math.random() * 100, emoji: emoji });
  }

  var lastFrame = null;

  function frame(now) {
    if (!ctx || !canvas) return;
    if (lastFrame === null) lastFrame = now;
    var dt = now - lastFrame;
    lastFrame = now;

    var width = canvas.width;
    var height = canvas.height;
    ctx.clearRect(0, 0, width, height);

    drawRoad(width, height, dt);

    if (now - lastObstacleAt > 3000) {
      spawnObstacle(width);
      lastObstacleAt = now;
    }
    obstacles = obstacles.filter(function (o) {
      o.x -= dt * 0.12;
      if (o.x < -20) return false;
      ctx.font = "24px serif";
      ctx.fillText(o.emoji, o.x, o.y);
      return true;
    });

    var boostFactor = now < state.boostUntil ? 1.15 : 1.0;
    var pct = Math.max(0, Math.min(100, state.progressPct * boostFactor));
    var trackWidth = width - 60;
    var shipX = 30 + (trackWidth * pct) / 100;
    drawShip(shipX, height - 30);

    if (state.status === "done") {
      ctx.font = "16px sans-serif";
      ctx.fillStyle = "#49f7a5"; // --green
      ctx.fillText("🏁", width - 40, height - 30);
    }

    if (!state.finished || state.status === "done") {
      requestAnimationFrame(frame);
    }
  }

  if (ctx) requestAnimationFrame(frame);
  poll();
})();
