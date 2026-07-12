// Channel Parser step 2 — polls job status and drives a small canvas Snake
// game while the user waits (TZ_CHANNELS.md §3.3). Vanilla JS, no external
// libraries. Tick speed is tied to the real progress_pct from the API, not
// to input — arrow keys/WASD only steer, they don't speed anything up.
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
  };

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
      setTimeout(function () {
        window.location.href = "/channels/parse/" + jobId + "/results";
      }, 800);
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

  // --- Mini-game: Snake, score counts food eaten. Tick speed is driven by
  // state.progressPct (updated from real polling above); arrow keys/WASD
  // only steer, they never change how fast it ticks. ---

  var GRID_SIZE = 20;
  var COLS = canvas ? Math.floor(canvas.width / GRID_SIZE) : 0;
  var ROWS = canvas ? Math.floor(canvas.height / GRID_SIZE) : 0;
  var MIN_TICK_MS = 90;
  var MAX_TICK_MS = 260;

  var snake = [
    { x: 6, y: 5 },
    { x: 5, y: 5 },
    { x: 4, y: 5 },
  ];
  var direction = { x: 1, y: 0 };
  var pendingDirection = direction;
  var food = { x: 20, y: 5 };
  var score = 0;
  var lastTick = 0;

  function cellsEqual(a, b) {
    return a.x === b.x && a.y === b.y;
  }

  function isOnSnake(cell) {
    return snake.some(function (segment) {
      return cellsEqual(segment, cell);
    });
  }

  function respawnFood() {
    var next = { x: Math.floor(Math.random() * COLS), y: Math.floor(Math.random() * ROWS) };
    while (isOnSnake(next)) {
      next = { x: Math.floor(Math.random() * COLS), y: Math.floor(Math.random() * ROWS) };
    }
    food = next;
  }

  function setDirection(dx, dy) {
    if (direction.x === -dx && direction.y === -dy) return; // no instant 180s
    pendingDirection = { x: dx, y: dy };
  }

  window.addEventListener("keydown", function (e) {
    if (e.key === "ArrowUp" || e.key === "w" || e.key === "W") {
      e.preventDefault();
      setDirection(0, -1);
    } else if (e.key === "ArrowDown" || e.key === "s" || e.key === "S") {
      e.preventDefault();
      setDirection(0, 1);
    } else if (e.key === "ArrowLeft" || e.key === "a" || e.key === "A") {
      e.preventDefault();
      setDirection(-1, 0);
    } else if (e.key === "ArrowRight" || e.key === "d" || e.key === "D") {
      e.preventDefault();
      setDirection(1, 0);
    }
  });

  function tickIntervalMs() {
    var pct = Math.max(0, Math.min(100, state.progressPct));
    return MAX_TICK_MS - (pct / 100) * (MAX_TICK_MS - MIN_TICK_MS);
  }

  function tickSnake() {
    direction = pendingDirection;
    var head = snake[0];
    var next = {
      x: (head.x + direction.x + COLS) % COLS,
      y: (head.y + direction.y + ROWS) % ROWS,
    };

    if (isOnSnake(next)) {
      // Self-collision: shrink back down instead of a hard game-over — this
      // is a decorative wait-timer, not a real game with a losing state.
      snake = snake.slice(0, 3);
      return;
    }

    snake.unshift(next);
    if (cellsEqual(next, food)) {
      score += 1;
      respawnFood();
    } else {
      snake.pop();
    }
  }

  function drawSnakeGame() {
    var width = canvas.width;
    var height = canvas.height;
    ctx.clearRect(0, 0, width, height);

    ctx.font = (GRID_SIZE - 2) + "px serif";
    ctx.fillText("🍎", food.x * GRID_SIZE + 1, food.y * GRID_SIZE + GRID_SIZE - 3);

    ctx.fillStyle = "#ff5c45"; // --accent
    snake.forEach(function (segment, i) {
      var pad = i === 0 ? 1 : 2;
      ctx.fillRect(
        segment.x * GRID_SIZE + pad,
        segment.y * GRID_SIZE + pad,
        GRID_SIZE - pad * 2,
        GRID_SIZE - pad * 2
      );
    });

    ctx.font = "14px monospace";
    ctx.fillStyle = "#f4f2ec"; // --text
    ctx.fillText("Score: " + score, 8, 16);
  }

  function frame(now) {
    if (!ctx || !canvas) return;
    if (now - lastTick > tickIntervalMs()) {
      tickSnake();
      lastTick = now;
    }
    drawSnakeGame();

    if (!state.finished || state.status === "done") {
      requestAnimationFrame(frame);
    }
  }

  if (ctx) {
    respawnFood();
    requestAnimationFrame(frame);
  }
  poll();
})();
