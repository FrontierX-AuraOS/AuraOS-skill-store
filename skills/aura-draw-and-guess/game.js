"use strict";

const SESSION_KEY = "aura-draw-and-guess-session";
const svgNamespace = "http://www.w3.org/2000/svg";

const ui = {
  startView: document.querySelector("#start-view"),
  gameView: document.querySelector("#game-view"),
  startButton: document.querySelector("#start-button"),
  webOnlyModeInput: document.querySelector('input[value="web_only"]'),
  webDuelModeInput: document.querySelector('input[value="web_duel"]'),
  cameraModeOption: document.querySelector("#camera-mode-option"),
  cameraModeInput: document.querySelector('input[value="robot_camera"]'),
  cameraModeDetail: document.querySelector("#camera-mode-detail"),
  startCapabilities: document.querySelector("#start-capabilities"),
  connection: document.querySelector("#connection-state"),
  roundTitle: document.querySelector("#round-title"),
  roleCopy: document.querySelector("#role-copy"),
  phaseChip: document.querySelector("#phase-chip"),
  countdown: document.querySelector("#countdown"),
  userScore: document.querySelector("#user-score"),
  agentScore: document.querySelector("#agent-score"),
  strokeProgress: document.querySelector("#stroke-progress"),
  displayStatus: document.querySelector("#display-status"),
  canvas: document.querySelector("#drawing-canvas"),
  drawingPrompt: document.querySelector("#drawing-prompt"),
  physicalDrawing: document.querySelector("#physical-drawing"),
  answerReveal: document.querySelector("#answer-reveal"),
  continueDrawingButton: document.querySelector("#continue-drawing-button"),
  clearDrawingButton: document.querySelector("#clear-drawing-button"),
  guessHistory: document.querySelector("#guess-history"),
  dialogueLog: document.querySelector("#dialogue-log"),
  dialogueMode: document.querySelector("#dialogue-mode"),
  ttsState: document.querySelector("#tts-state"),
  guessForm: document.querySelector("#guess-form"),
  guessInput: document.querySelector("#guess-input"),
  voiceButton: document.querySelector("#voice-button"),
  endRoundButton: document.querySelector("#end-round-button"),
  cameraActions: document.querySelector("#camera-actions"),
  cameraStatusCopy: document.querySelector("#camera-status-copy"),
  cameraGuessButton: document.querySelector("#camera-guess-button"),
  cameraFallbackButton: document.querySelector("#camera-fallback-button"),
  webDrawingActions: document.querySelector("#web-drawing-actions"),
  webDrawingStatus: document.querySelector("#web-drawing-status"),
  canvasGuessButton: document.querySelector("#canvas-guess-button"),
  visualFallbackButton: document.querySelector("#visual-fallback-button"),
  nextRoundButton: document.querySelector("#next-round-button"),
  summaryBand: document.querySelector("#summary-band"),
  summaryTitle: document.querySelector("#summary-title"),
  summaryCopy: document.querySelector("#summary-copy"),
  roundRecap: document.querySelector("#round-recap"),
  restartButton: document.querySelector("#restart-button"),
  capabilityRail: document.querySelector("#capability-rail"),
  errorBanner: document.querySelector("#error-banner"),
  roundMarkers: [...document.querySelectorAll("[data-round-marker]")],
  modeOptions: [...document.querySelectorAll(".mode-option")],
};

let state = null;
let capabilities = null;
let mutationInFlight = false;
let pollTimer = null;
let errorTimer = null;
let agentReplyPending = false;

const renderCache = {
  canvasKey: "",
  capabilities: "",
  dialogueSequences: [],
  guessKey: "",
  guessCount: 0,
  summaryKey: "",
};

const drawing = {
  key: "",
  strokes: [],
  serverSignature: "",
  active: null,
};

function requestId() {
  if (crypto.randomUUID) return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(payload.error?.message || `HTTP ${response.status}`);
    error.code = payload.error?.code;
    error.latestState = payload.state;
    throw error;
  }
  return payload;
}

async function loadCapabilities() {
  try {
    capabilities = await api("/api/capabilities", { headers: { Accept: "application/json" } });
    renderCapabilities(capabilities);
    setConnection(capabilities.daemon?.available ? "ready" : "fallback", capabilities.daemon?.available ? "Daemon 已连接" : "网页模式可用");
  } catch (error) {
    setConnection("error", "游戏服务不可用");
    showError(error.message);
  }
}

function renderCapabilities(items) {
  const signature = JSON.stringify(items);
  if (signature === renderCache.capabilities) return;
  renderCache.capabilities = signature;
  const robotReady = Boolean(items.robot_camera?.available);
  if (!state && items.vision?.available && ui.webOnlyModeInput.checked) {
    ui.webOnlyModeInput.checked = false;
    ui.webDuelModeInput.checked = true;
    ui.modeOptions.forEach((option) => option.classList.toggle("active", option.contains(ui.webDuelModeInput)));
  }
  ui.cameraModeInput.disabled = !robotReady;
  ui.cameraModeOption.classList.toggle("disabled", !robotReady);
  ui.cameraModeDetail.textContent = items.robot_camera?.detail || "能力未知";
  const agentReady = Boolean(items.dialogue_agent?.available);
  const agentAttemptable = Boolean(items.dialogue_agent?.attemptable);
  ui.startCapabilities.textContent = agentReady
    ? "AuraOS Agent 对话已连接 · 网页作画可用"
    : agentAttemptable ? "AuraOS Agent 将在首次猜错时验证 · 网页作画可用" : "网页玩法可运行 · Agent 模型与视觉能力将诚实降级";

  const labels = [
    ["web", "网页"], ["web_drawing", "网页作画"], ["dialogue_agent", "对话模型"],
    ["vision", "视觉"], ["camera", "摄像头"], ["tts", "语音输出"],
    ["asr", "语音输入"], ["display", "机器人屏幕"],
  ];
  ui.capabilityRail.replaceChildren(...labels.map(([key, label]) => {
    const item = document.createElement("span");
    item.className = `capability-item${items[key]?.available ? " ready" : ""}`;
    item.title = items[key]?.detail || "";
    const dot = document.createElement("i");
    const copy = document.createElement("span");
    copy.textContent = `${label} · ${items[key]?.available ? "可用" : items[key]?.attemptable ? "待验证" : "降级"}`;
    item.append(dot, copy);
    return item;
  }));
}

function setConnection(kind, copy) {
  ui.connection.className = `connection-state ${kind}`;
  ui.connection.querySelector("span").textContent = copy;
}

function resetRenderCache() {
  renderCache.canvasKey = "";
  renderCache.dialogueSequences = [];
  renderCache.guessKey = "";
  renderCache.guessCount = 0;
  renderCache.summaryKey = "";
  drawing.key = "";
  drawing.strokes = [];
  drawing.serverSignature = "";
  drawing.active = null;
}

async function startGame(modeOverride = null) {
  const selected = modeOverride || document.querySelector('input[name="mode"]:checked')?.value || "web_only";
  ui.startButton.disabled = true;
  try {
    state = await api("/api/sessions", { method: "POST", body: JSON.stringify({ mode: selected }) });
    sessionStorage.setItem(SESSION_KEY, state.session_id);
    resetRenderCache();
    showGame();
    render();
    startPolling();
  } catch (error) {
    showError(error.message);
  } finally {
    ui.startButton.disabled = false;
  }
}

async function restoreSession() {
  const sessionId = sessionStorage.getItem(SESSION_KEY);
  if (!sessionId) return false;
  try {
    state = await api(`/api/sessions/${sessionId}`, { headers: { Accept: "application/json" } });
    capabilities = state.capabilities;
    resetRenderCache();
    showGame();
    render();
    startPolling();
    return true;
  } catch {
    sessionStorage.removeItem(SESSION_KEY);
    return false;
  }
}

function showGame() {
  ui.startView.classList.add("hidden");
  ui.gameView.classList.remove("hidden");
}

async function mutate(action, extra = {}) {
  if (!state) return null;
  while (mutationInFlight) await new Promise((resolve) => setTimeout(resolve, 20));
  mutationInFlight = true;
  try {
    const next = await api(`/api/sessions/${state.session_id}/${action}`, {
      method: "POST",
      body: JSON.stringify({ request_id: requestId(), expected_sequence: state.sequence, ...extra }),
    });
    state = next;
    render();
    return next;
  } catch (error) {
    if (error.latestState) {
      state = error.latestState;
      render();
    }
    if (error.code !== "sequence_conflict") showError(error.message);
    return null;
  } finally {
    mutationInFlight = false;
    if (state) renderControls(state.current_round);
  }
}

function startPolling() {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    if (!state) return;
    const polledSession = state.session_id;
    try {
      const next = await api(`/api/sessions/${polledSession}`, { headers: { Accept: "application/json" } });
      if (!state || state.session_id !== polledSession) return;
      if (next.sequence >= state.sequence && (next.sequence !== state.sequence || next.current_round.seconds_remaining !== state.current_round.seconds_remaining)) {
        state = next;
        render();
      }
    } catch (error) {
      showError(error.message);
    }
  }, 1000);
}

function render() {
  if (!state) return;
  const round = state.current_round;
  ui.roundTitle.textContent = `第 ${state.round} 回合`;
  ui.roleCopy.textContent = round.drawer === "agent" ? "Agent 作画 · 你来猜" : "你来作画 · Agent 猜";
  ui.phaseChip.textContent = phaseLabel(state.phase);
  ui.countdown.textContent = formatTime(round.seconds_remaining);
  ui.userScore.textContent = String(state.score.user_score);
  ui.agentScore.textContent = state.score.agent_participated ? String(state.score.agent_score) : "—";
  ui.ttsState.textContent = state.capabilities.tts?.available ? "TTS 同步" : "文字模式";
  ui.dialogueMode.textContent = state.capabilities.dialogue_agent?.available
    ? "AURAOS AGENT" : state.capabilities.dialogue_agent?.attemptable ? "AURAOS AGENT · 待验证" : "LOCAL FALLBACK";
  ui.displayStatus.textContent = round.display_status === "unavailable" ? "机器人屏幕待接入" : "机器人屏幕已同步";

  ui.roundMarkers.forEach((marker, index) => {
    marker.classList.toggle("current", index + 1 === state.round && state.state !== "finished");
    marker.classList.toggle("complete", state.rounds[index]?.status === "result");
  });
  renderCanvas(round);
  renderGuesses(round.guess_history);
  renderDialogue(state.events);
  renderControls(round);
  renderCapabilities(state.capabilities);
  renderSummary();
}

function createSvgPath(pathData, width = 7, color = "#202420") {
  const path = document.createElementNS(svgNamespace, "path");
  path.setAttribute("d", pathData);
  path.setAttribute("stroke", color);
  path.setAttribute("stroke-width", String(width));
  return path;
}

function pointsToPath(points) {
  return points.map((point, index) => `${index ? "L" : "M"}${point[0]} ${point[1]}`).join(" ");
}

function renderCanvas(round) {
  const key = `${state.session_id}:${state.round}:${round.drawer}:${round.drawing_source}`;
  if (renderCache.canvasKey !== key) {
    renderCache.canvasKey = key;
    ui.canvas.replaceChildren();
    drawing.key = "";
  }
  if (round.drawer === "agent") {
    const visible = round.canvas.strokeSequence.slice(0, round.canvas.currentStrokeIndex);
    if (ui.canvas.childElementCount > visible.length) ui.canvas.replaceChildren();
    for (let index = ui.canvas.childElementCount; index < visible.length; index += 1) {
      const stroke = visible[index];
      ui.canvas.append(createSvgPath(stroke.path, stroke.width, stroke.color));
    }
  } else if (round.drawing_source === "web_canvas") {
    const serverStrokes = round.canvas.userStrokes || [];
    const signature = JSON.stringify(serverStrokes);
    if (drawing.key !== key || (!drawing.active && drawing.serverSignature !== signature)) {
      drawing.key = key;
      drawing.strokes = structuredClone(serverStrokes);
      drawing.serverSignature = signature;
      ui.canvas.replaceChildren(...drawing.strokes.map((stroke) => createSvgPath(pointsToPath(stroke.points), stroke.width, stroke.color)));
    }
  }

  const isWebDrawing = round.drawer === "user" && round.drawing_source === "web_canvas" && round.status === "user_drawing";
  ui.canvas.classList.toggle("user-drawing", isWebDrawing);
  ui.canvas.setAttribute("aria-label", isWebDrawing ? "你的网页绘图画布" : "Agent 正在逐步绘制的画面");
  ui.strokeProgress.textContent = round.drawer === "agent"
    ? `${round.canvas.currentStrokeIndex} / ${round.canvas.strokeSequence.length} 笔`
    : round.drawing_source === "web_canvas" ? `${round.canvas.userStrokes.length} 笔 · 网页画布` : "摄像头画面";
  ui.physicalDrawing.classList.toggle("hidden", round.drawer !== "user" || round.drawing_source !== "camera" || round.status === "result");
  ui.drawingPrompt.classList.toggle("hidden", !isWebDrawing || !round.drawing_prompt);
  ui.drawingPrompt.textContent = round.drawing_prompt ? `你的题目：${round.drawing_prompt}` : "";
  ui.answerReveal.classList.toggle("hidden", !round.revealed_answer);
  ui.answerReveal.textContent = round.revealed_answer ? `答案 · ${round.revealed_answer}` : "";
}

function renderGuesses(history) {
  const key = `${state.session_id}:${state.round}`;
  if (renderCache.guessKey !== key || renderCache.guessCount > history.length) {
    renderCache.guessKey = key;
    renderCache.guessCount = 0;
    ui.guessHistory.replaceChildren();
  }
  for (let index = renderCache.guessCount; index < history.length; index += 1) {
    const guess = history[index];
    const item = document.createElement("span");
    item.className = `guess-pill${guess.correct ? " correct" : ""}`;
    if (["camera", "web_canvas"].includes(guess.source)) {
      const source = guess.source === "camera" ? "摄像头" : "网页画布";
      item.textContent = `Agent · ${source} · ${guess.correct ? "命中" : "未命中"} · ${Math.round((guess.confidence || 0) * 100)}%`;
    } else {
      item.textContent = `${guess.source === "asr" ? "语音" : "猜测"} · ${guess.text} · ${guess.correct ? "正确" : "再想想"}`;
    }
    ui.guessHistory.append(item);
  }
  renderCache.guessCount = history.length;
}

function renderDialogue(events) {
  const messages = events.filter((event) => event.text && (event.dialogue || event.type === "voice_transcript" || event.type === "capability_error"));
  const sequences = messages.map((event) => event.sequence);
  const prefixMatches = renderCache.dialogueSequences.every((sequence, index) => sequences[index] === sequence);
  if (!prefixMatches || renderCache.dialogueSequences.length > sequences.length) {
    ui.dialogueLog.replaceChildren();
    renderCache.dialogueSequences = [];
  }
  const start = renderCache.dialogueSequences.length;
  for (let index = start; index < messages.length; index += 1) {
    const event = messages[index];
    const item = document.createElement("article");
    item.className = "dialogue-message";
    const meta = document.createElement("div");
    meta.className = "dialogue-meta";
    const phase = document.createElement("span");
    phase.textContent = `R${event.round} · ${phaseLabel(event.phase)}`;
    const source = document.createElement("span");
    source.textContent = event.dialogue_source === "auraos_model" ? "AuraOS Agent" : ttsLabel(event.tts_status);
    const copy = document.createElement("p");
    copy.textContent = event.type === "voice_transcript" ? `识别结果：“${event.text}”` : event.text;
    meta.append(phase, source);
    item.append(meta, copy);
    ui.dialogueLog.append(item);
  }
  if (messages.length > start) ui.dialogueLog.scrollTop = ui.dialogueLog.scrollHeight;
  renderCache.dialogueSequences = sequences;
}

function renderControls(round) {
  const active = state.state === "active" && round.status !== "result";
  const userGuessing = active && round.guesser === "user";
  const cameraRound = active && round.drawer === "user" && round.drawing_source === "camera";
  const webDrawingRound = active && round.drawer === "user" && round.drawing_source === "web_canvas";
  const agentCanDraw = active && round.drawer === "agent" && round.status === "drawing";
  const visionReady = Boolean(state.capabilities.vision?.available);
  ui.guessForm.classList.toggle("hidden", !userGuessing);
  ui.cameraActions.classList.toggle("hidden", !cameraRound);
  ui.webDrawingActions.classList.toggle("hidden", !webDrawingRound);
  ui.nextRoundButton.classList.toggle("hidden", round.status !== "result" || state.state === "finished");
  ui.continueDrawingButton.classList.toggle("hidden", !agentCanDraw);
  ui.clearDrawingButton.classList.toggle("hidden", !webDrawingRound || round.status !== "user_drawing");
  ui.voiceButton.classList.toggle("hidden", !userGuessing || !state.capabilities.asr?.available);
  ui.guessInput.disabled = !userGuessing || mutationInFlight || agentReplyPending;
  ui.continueDrawingButton.disabled = mutationInFlight;
  ui.clearDrawingButton.disabled = mutationInFlight;
  ui.cameraGuessButton.disabled = mutationInFlight || round.status === "camera_processing";
  ui.cameraFallbackButton.disabled = mutationInFlight;
  ui.canvasGuessButton.disabled = mutationInFlight || !visionReady || round.canvas.userStrokes.length === 0 || round.status === "visual_processing";
  ui.visualFallbackButton.disabled = mutationInFlight;
  ui.endRoundButton.disabled = mutationInFlight;

  const visualEvent = [...state.events].reverse().find((event) => event.round === state.round && ["camera_status", "visual_status"].includes(event.type));
  const steps = {
    capturing: "拍摄中 · 正在从 AuraOS Daemon 获取 JPEG",
    recognizing: "识别中 · AuraOS 视觉模型正在选择候选",
    judging: "判定中 · 服务端正在核对结果并计分",
  };
  ui.cameraStatusCopy.textContent = ["camera_processing", "visual_processing"].includes(round.status)
    ? (steps[visualEvent?.status] || "视觉流程处理中") : "画好后拍摄，Agent 将从受限候选中猜一次。";
  ui.webDrawingStatus.textContent = round.status === "visual_processing"
    ? (steps[visualEvent?.status] || "AuraOS 视觉模型处理中")
    : visionReady
      ? "画好后将 PNG 交给 AuraOS 视觉模型。"
      : `${state.capabilities.vision?.detail || "AuraOS 视觉服务不可用"}；可继续画或切换为你来猜。`;
}

function renderSummary() {
  const finished = state.state === "finished";
  ui.summaryBand.classList.toggle("hidden", !finished);
  if (!finished) return;
  const key = `${state.session_id}:${state.sequence}`;
  if (renderCache.summaryKey === key) return;
  renderCache.summaryKey = key;
  const summary = [...state.events].reverse().find((event) => event.type === "game_summary");
  const title = { user: "你赢了", agent: "Agent 赢了", tie: "平局", not_applicable: "六回合完成" }[state.champion] || "六回合结束";
  ui.summaryTitle.textContent = title;
  ui.summaryCopy.textContent = summary?.text || "本局已经完成。";
  ui.roundRecap.replaceChildren(...state.rounds.map((round) => {
    const item = document.createElement("div");
    item.className = "recap-item";
    const number = document.createElement("span");
    number.textContent = `ROUND ${round.round}`;
    const answer = document.createElement("strong");
    answer.textContent = round.revealed_answer || "—";
    const result = document.createElement("small");
    result.textContent = resultLabel(round.result, round.points_awarded);
    item.append(number, answer, result);
    return item;
  }));
  ui.summaryBand.scrollIntoView({ behavior: "smooth", block: "start" });
}

function phaseLabel(phase) {
  return {
    round_started: "回合开始", drawing: "绘制中", drawing_midpoint: "绘制中",
    drawing_complete: "等待猜测", guessing: "等待猜测", user_drawing: "你在作画",
    awaiting_camera: "等待拍摄", camera_processing: "识别中", visual_processing: "识别中",
    guess_submitted: "判定中", guess_result: "猜测结果", round_result: "回合结算",
    game_summary: "全局总结", result: "回合结算",
  }[phase] || phase;
}

function ttsLabel(status) {
  return { spoken: "已播报", queued: "待播报", auraos_agent: "AuraOS 同步", unavailable: "仅文字", error: "播报失败" }[status] || "仅文字";
}

function resultLabel(result, points) {
  if (result === "correct") return points ? "猜中 · +1" : "猜中";
  if (result === "timeout") return "超时结束";
  if (result === "incorrect") return "未猜中";
  return "主动结束";
}

function formatTime(seconds) {
  const safe = Math.max(0, Number(seconds) || 0);
  return `${String(Math.floor(safe / 60)).padStart(2, "0")}:${String(safe % 60).padStart(2, "0")}`;
}

function showError(message) {
  clearTimeout(errorTimer);
  ui.errorBanner.textContent = message;
  ui.errorBanner.classList.remove("hidden");
  errorTimer = setTimeout(() => ui.errorBanner.classList.add("hidden"), 5000);
}

function canvasPoint(event) {
  const rect = ui.canvas.getBoundingClientRect();
  return [
    Math.max(0, Math.min(640, ((event.clientX - rect.left) / rect.width) * 640)),
    Math.max(0, Math.min(420, ((event.clientY - rect.top) / rect.height) * 420)),
  ].map((value) => Math.round(value * 10) / 10);
}

function canUserDraw() {
  const round = state?.current_round;
  return Boolean(round && round.drawer === "user" && round.drawing_source === "web_canvas" && round.status === "user_drawing" && !mutationInFlight);
}

ui.canvas.addEventListener("pointerdown", (event) => {
  if (!canUserDraw()) return;
  event.preventDefault();
  ui.canvas.setPointerCapture(event.pointerId);
  const point = canvasPoint(event);
  const stroke = { points: [point], width: 7, color: "#202420" };
  const path = createSvgPath(pointsToPath([point, point]), stroke.width, stroke.color);
  ui.canvas.append(path);
  drawing.active = { pointerId: event.pointerId, stroke, path };
});

ui.canvas.addEventListener("pointermove", (event) => {
  const active = drawing.active;
  if (!active || active.pointerId !== event.pointerId) return;
  event.preventDefault();
  const point = canvasPoint(event);
  const previous = active.stroke.points[active.stroke.points.length - 1];
  if (Math.hypot(point[0] - previous[0], point[1] - previous[1]) < 1.5) return;
  active.stroke.points.push(point);
  active.path.setAttribute("d", pointsToPath(active.stroke.points));
});

async function finishPointer(event) {
  const active = drawing.active;
  if (!active || active.pointerId !== event.pointerId) return;
  event.preventDefault();
  if (active.stroke.points.length === 1) active.stroke.points.push([active.stroke.points[0][0] + 0.1, active.stroke.points[0][1] + 0.1]);
  drawing.strokes.push(active.stroke);
  drawing.active = null;
  const result = await mutate("drawing/save", { strokes: drawing.strokes });
  if (result) drawing.serverSignature = JSON.stringify(result.current_round.canvas.userStrokes || []);
}

ui.canvas.addEventListener("pointerup", finishPointer);
ui.canvas.addEventListener("pointercancel", finishPointer);

function drawingPng() {
  const canvas = document.createElement("canvas");
  canvas.width = 640;
  canvas.height = 420;
  const context = canvas.getContext("2d");
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.lineCap = "round";
  context.lineJoin = "round";
  drawing.strokes.forEach((stroke) => {
    if (stroke.points.length < 2) return;
    context.beginPath();
    context.moveTo(stroke.points[0][0], stroke.points[0][1]);
    stroke.points.slice(1).forEach((point) => context.lineTo(point[0], point[1]));
    context.strokeStyle = stroke.color;
    context.lineWidth = stroke.width;
    context.stroke();
  });
  return canvas.toDataURL("image/png");
}

ui.modeOptions.forEach((option) => {
  option.addEventListener("click", () => {
    const input = option.querySelector("input");
    if (input?.disabled) return;
    ui.modeOptions.forEach((item) => item.classList.remove("active"));
    option.classList.add("active");
  });
});

ui.startButton.addEventListener("click", () => startGame());
ui.continueDrawingButton.addEventListener("click", () => mutate("draw/advance"));
ui.clearDrawingButton.addEventListener("click", async () => {
  drawing.strokes = [];
  drawing.active = null;
  ui.canvas.replaceChildren();
  const result = await mutate("drawing/save", { strokes: [] });
  if (result) drawing.serverSignature = JSON.stringify([]);
});
ui.guessForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const guess = ui.guessInput.value.trim();
  if (!guess) {
    showError("先写下你的猜测");
    ui.guessInput.focus();
    return;
  }
  const result = await mutate("guess", { guess });
  if (!result) return;
  ui.guessInput.value = "";
  if (result.guess_result && !result.guess_result.correct) {
    agentReplyPending = true;
    ui.dialogueMode.textContent = result.capabilities.dialogue_agent?.attemptable ? "AURAOS AGENT · 回应中" : "LOCAL FALLBACK · 回应中";
    renderControls(result.current_round);
    await mutate("agent-reply", { guess });
    agentReplyPending = false;
    render();
  }
});
ui.voiceButton.addEventListener("click", () => mutate("voice-guess"));
ui.endRoundButton.addEventListener("click", () => mutate("round/end"));
ui.cameraGuessButton.addEventListener("click", () => mutate("camera-guess"));
ui.cameraFallbackButton.addEventListener("click", () => mutate("visual-fallback"));
ui.canvasGuessButton.addEventListener("click", () => mutate("canvas-guess", { image: drawingPng() }));
ui.visualFallbackButton.addEventListener("click", () => mutate("visual-fallback"));
ui.nextRoundButton.addEventListener("click", () => mutate("round/next"));
ui.restartButton.addEventListener("click", () => startGame(state?.mode || "web_only"));

window.addEventListener("beforeunload", () => clearInterval(pollTimer));

(async function boot() {
  await loadCapabilities();
  await restoreSession();
})();
