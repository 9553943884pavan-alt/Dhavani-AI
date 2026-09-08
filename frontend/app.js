/**
 * Voice Latency Demo — Real-time Frontend Client
 * Handles push-to-talk mic recording, WebSocket bidirectional streaming,
 * accumulated audio playback via standard HTML <audio> element, and telemetry logging.
 */

// State
let ws = null;
let currentMode = "optimized"; // "optimized" or "naive"
let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;
let isStartingRecording = false;
let isPipelineActive = false;
let shouldStopAfterRecordingStarts = false;
let audioPlaybackUnlocked = false;

// Audio playback state (accumulated chunks -> Blob -> HTMLAudioElement)
let receivedAudioChunks = []; // Array of Uint8Arrays accumulating audio bytes for current response
let currentAudioElement = null; // Currently playing standard HTML <audio> element
let streamingMediaSource = null;
let streamingSourceBuffer = null;
let streamingAudioUrl = null;
let streamingAudioQueue = [];
let streamingAudioDone = false;

// Benchmark memory for side-by-side comparison
let lastNaiveT3 = null;
let lastOptimizedT3 = null;

// DOM Elements
const micBtn = document.getElementById("micBtn");
const micTip = document.getElementById("micTip");
const textInput = document.getElementById("textInput");
const sendBtn = document.getElementById("sendBtn");
const userTranscriptEl = document.getElementById("userTranscript");
const assistantResponseEl = document.getElementById("assistantResponse");
const streamingCursor = document.getElementById("streamingCursor");
const audioStatusDot = document.getElementById("audioStatusDot");
const audioStatusText = document.getElementById("audioStatusText");

// Metric Elements
const t0Val = document.getElementById("t0Val");
const t1Val = document.getElementById("t1Val");
const t2Val = document.getElementById("t2Val");
const t3Val = document.getElementById("t3Val");
const compDiffVal = document.getElementById("compDiffVal");
const compBarFill = document.getElementById("compBarFill");

// Mode buttons
const optBtn = document.getElementById("optBtn");
const naiveBtn = document.getElementById("naiveBtn");
const modeTitleEl = document.getElementById("modeTitle");
const modeDescEl = document.getElementById("modeDesc");

// Stop and cleanup any currently playing audio
function stopCurrentAudio() {
    try {
        if (currentAudioElement) {
            currentAudioElement.pause();
        }
        if (streamingMediaSource && streamingMediaSource.readyState === "open") {
            streamingMediaSource.endOfStream();
        }
        if (streamingAudioUrl) {
            URL.revokeObjectURL(streamingAudioUrl);
            streamingAudioUrl = null;
        }
        if (currentAudioElement) {
            currentAudioElement.removeAttribute("src");
        }
        currentAudioElement = null;
        streamingMediaSource = null;
        streamingSourceBuffer = null;
        streamingAudioQueue = [];
        streamingAudioDone = false;
    } catch (err) {
        console.error("Error stopping current audio element:", err);
    }
}

function primeAudioPlayback() {
    try {
        const audio = new Audio();
        audio.volume = 0.01;
        audio.src = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAESsAAABAAgAZGF0YQAAAAA=";
        const playPromise = audio.play();
        if (playPromise !== undefined) {
            playPromise.then(() => {
                audioPlaybackUnlocked = true;
                if (streamingAudioQueue.length > 0) {
                    startStreamingAudioPlayback();
                    flushStreamingAudioQueue();
                }
            }).catch((err) => {
                console.warn("Audible audio playback was not unlocked:", err);
            }).finally(() => {
                audio.pause();
                audio.removeAttribute("src");
            });
        }
    } catch (err) {
        console.warn("Audio playback could not be primed:", err);
    }
}

// Accumulate received audio chunk
function handleAudioChunk(arrayBuffer) {
    try {
        const uint8Chunk = new Uint8Array(arrayBuffer);
        if (currentMode === "optimized" && MediaSource.isTypeSupported("audio/mpeg")) {
            streamingAudioQueue.push(uint8Chunk);
            startStreamingAudioPlayback();
            flushStreamingAudioQueue();
        } else {
            receivedAudioChunks.push(uint8Chunk);
        }
    } catch (err) {
        console.error("Error accumulating audio chunk into Uint8Array:", err);
    }
}

function startStreamingAudioPlayback() {
    if (currentAudioElement || !audioPlaybackUnlocked || streamingMediaSource) return;

    streamingMediaSource = new MediaSource();
    streamingAudioUrl = URL.createObjectURL(streamingMediaSource);
    const audio = new Audio(streamingAudioUrl);
    currentAudioElement = audio;
    audioStatusDot.classList.add("playing");
    audioStatusText.textContent = "Playing synthesized audio...";

    audio.onended = () => {
        stopCurrentAudio();
        audioStatusDot.classList.remove("playing");
        audioStatusText.textContent = "Audio idle";
    };
    audio.onerror = (event) => {
        console.error("Streaming audio playback error:", event, audio.error);
        stopCurrentAudio();
        audioStatusDot.classList.remove("playing");
        audioStatusText.textContent = "Audio playback error";
    };

    streamingMediaSource.addEventListener("sourceopen", () => {
        if (!streamingMediaSource || streamingSourceBuffer) return;
        try {
            streamingSourceBuffer = streamingMediaSource.addSourceBuffer("audio/mpeg");
            streamingSourceBuffer.addEventListener("updateend", flushStreamingAudioQueue);
            flushStreamingAudioQueue();
            const playPromise = audio.play();
            if (playPromise !== undefined) {
                playPromise.catch((err) => {
                    console.error("Streaming audio.play() rejected:", err);
                    audioStatusText.textContent = "Audio playback failed";
                });
            }
        } catch (err) {
            console.error("Could not initialize streaming audio buffer:", err);
            audioStatusText.textContent = "Streaming audio is not supported by this browser";
        }
    }, { once: true });
}

function flushStreamingAudioQueue() {
    if (!streamingSourceBuffer || streamingSourceBuffer.updating || streamingAudioQueue.length === 0) {
        if (streamingAudioDone && streamingSourceBuffer && !streamingSourceBuffer.updating && streamingAudioQueue.length === 0 && streamingMediaSource.readyState === "open") {
            streamingMediaSource.endOfStream();
        }
        return;
    }
    streamingSourceBuffer.appendBuffer(streamingAudioQueue.shift());
}

// Play accumulated audio chunks when "done" event is received
function playAccumulatedAudio() {
    let audioUrl = null;
    let audio = null;
    try {
        if (!receivedAudioChunks || receivedAudioChunks.length === 0) {
            console.warn("No audio chunks accumulated to play.");
            audioStatusDot.classList.remove("playing");
            audioStatusText.textContent = "Audio idle";
            return;
        }

        stopCurrentAudio();

        audioStatusDot.classList.add("playing");
        audioStatusText.textContent = "Playing synthesized audio...";

        // Concatenate all accumulated Uint8Array chunks into a single Blob with type "audio/mpeg"
        const audioBlob = new Blob(receivedAudioChunks, { type: "audio/mpeg" });
        audioUrl = URL.createObjectURL(audioBlob);

        audio = new Audio(audioUrl);
        currentAudioElement = audio;

        audio.onended = () => {
            try {
                URL.revokeObjectURL(audioUrl);
                audioStatusDot.classList.remove("playing");
                audioStatusText.textContent = "Audio idle";
                if (currentAudioElement === audio) {
                    currentAudioElement = null;
                }
            } catch (err) {
                console.error("Error in audio.onended handler:", err);
            }
        };

        audio.onerror = (e) => {
            try {
                console.error("HTMLAudioElement playback error:", e, audio.error);
                URL.revokeObjectURL(audioUrl);
                audioStatusDot.classList.remove("playing");
                audioStatusText.textContent = "Audio playback error";
                if (currentAudioElement === audio) {
                    currentAudioElement = null;
                }
            } catch (err) {
                console.error("Error in audio.onerror handler:", err);
            }
        };

        if (!audioPlaybackUnlocked) {
            audioStatusDot.classList.remove("playing");
            audioStatusText.textContent = "Audio permission was blocked; click the microphone and try again";
            URL.revokeObjectURL(audioUrl);
            audio.removeAttribute("src");
            currentAudioElement = null;
            return;
        }

        const playPromise = audio.play();
        if (playPromise !== undefined) {
            playPromise.catch((err) => {
                console.error("audio.play() rejected:", err);
                URL.revokeObjectURL(audioUrl);
                audio.removeAttribute("src");
                if (currentAudioElement === audio) currentAudioElement = null;
                audioStatusDot.classList.remove("playing");
                audioStatusText.textContent = "Audio playback failed";
            });
        }
    } catch (err) {
        console.error("Fatal error during audio accumulation or playback:", err);
        if (audioUrl) URL.revokeObjectURL(audioUrl);
        if (audio) audio.removeAttribute("src");
        if (currentAudioElement === audio) currentAudioElement = null;
        audioStatusDot.classList.remove("playing");
        audioStatusText.textContent = "Audio playback error";
    }
}

function finishStreamingAudioPlayback() {
    streamingAudioDone = true;
    flushStreamingAudioQueue();
}

// WebSocket Setup
function initWebSocket() {
    try {
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const wsUrl = `${protocol}//${window.location.host}/ws/voice?mode=${currentMode}`;

        ws = new WebSocket(wsUrl);
        ws.binaryType = "arraybuffer";

        ws.onopen = () => {
            try {
                document.getElementById("connectionBadge").textContent = "Connected";
                document.getElementById("connectionBadge").className = "badge status";
            } catch (err) {
                console.error("Error updating connection badge on open:", err);
            }
        };

        ws.onclose = () => {
            try {
                isPipelineActive = false;
                document.getElementById("connectionBadge").textContent = "Reconnecting...";
                document.getElementById("connectionBadge").className = "badge";
                setTimeout(initWebSocket, 2000);
            } catch (err) {
                console.error("Error handling ws onclose:", err);
            }
        };

        ws.onerror = (err) => {
            console.error("WebSocket error:", err);
        };

        ws.onmessage = async (event) => {
            try {
                if (event.data instanceof ArrayBuffer) {
                    // Binary audio chunk received from server
                    handleAudioChunk(event.data);
                } else {
                    // JSON control message
                    let msg;
                    try {
                        msg = JSON.parse(event.data);
                    } catch (jsonErr) {
                        console.error("Error parsing WebSocket text message as JSON:", jsonErr, event.data);
                        return;
                    }
                    handleServerMessage(msg);
                }
            } catch (msgErr) {
                console.error("Unhandled error in WebSocket onmessage handler:", msgErr);
            }
        };
    } catch (initErr) {
        console.error("Error initializing WebSocket:", initErr);
    }
}

// Mode toggle
function setMode(mode) {
    try {
        currentMode = mode;
        if (mode === "optimized") {
            optBtn.classList.add("active", "optimized");
            naiveBtn.classList.remove("active", "naive");
            modeTitleEl.textContent = "Optimized Pipeline (Incremental WebSocket Streaming)";
            modeDescEl.textContent = "LLM tokens stream directly into Rime Mist v3 over WebSocket. Audio starts on the first word.";
        } else {
            naiveBtn.classList.add("active", "naive");
            optBtn.classList.remove("active", "optimized");
            modeTitleEl.textContent = "Naive Pipeline (Full-Response HTTP Baseline)";
            modeDescEl.textContent = "Waits for the LLM to finish generation completely, then calls Rime HTTP TTS.";
        }

        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ action: "set_mode", mode: currentMode }));
        }
    } catch (err) {
        console.error("Error setting mode:", err);
    }
}

optBtn.addEventListener("click", () => setMode("optimized"));
naiveBtn.addEventListener("click", () => setMode("naive"));

// Handle server events
function handleServerMessage(msg) {
    try {
        if (!msg || !msg.type) return;

        if (msg.type === "transcript") {
            userTranscriptEl.textContent = msg.text || "—";
            t1Val.textContent = msg.t1_ms ? `${msg.t1_ms.toFixed(0)} ms` : "0 ms";
        } else if (msg.type === "t2") {
            t2Val.textContent = `${msg.t2_ms.toFixed(0)} ms`;
        } else if (msg.type === "t3") {
            const t3 = msg.t3_ms;
            t3Val.textContent = `${t3.toFixed(0)} ms`;
            updateComparisonHUD(t3);
        } else if (msg.type === "llm_delta") {
            streamingCursor.style.display = "inline-block";
            assistantResponseEl.textContent += msg.delta;
        } else if (msg.type === "llm_text") {
            streamingCursor.style.display = "none";
            assistantResponseEl.textContent = msg.text;
            if (msg.t2_ms) t2Val.textContent = `${msg.t2_ms.toFixed(0)} ms`;
        } else if (msg.type === "timing") {
            const t3 = msg.t3_ms;
            t3Val.textContent = `${t3.toFixed(0)} ms`;
            updateComparisonHUD(t3);
            streamingCursor.style.display = "none";
        } else if (msg.type === "done") {
            isPipelineActive = false;
            streamingCursor.style.display = "none";
            if (currentMode === "optimized" && streamingMediaSource) {
                finishStreamingAudioPlayback();
            } else {
                playAccumulatedAudio();
            }
        } else if (msg.type === "error") {
            isPipelineActive = false;
            streamingCursor.style.display = "none";
            console.error("Server error message received:", msg.message);
            if (currentMode === "optimized" && streamingMediaSource) {
                finishStreamingAudioPlayback();
            } else if (receivedAudioChunks.length > 0) {
                playAccumulatedAudio();
            }
            alert("Server message: " + msg.message);
        }
    } catch (err) {
        console.error("Error in handleServerMessage:", err, msg);
    }
}

// Side-by-side comparison tracking
function updateComparisonHUD(newT3) {
    try {
        if (currentMode === "naive") {
            lastNaiveT3 = newT3;
        } else {
            lastOptimizedT3 = newT3;
        }

        if (lastNaiveT3 && lastOptimizedT3) {
            const diff = lastNaiveT3 - lastOptimizedT3;
            const pct = (diff / lastNaiveT3) * 100;
            if (diff > 0) {
                compDiffVal.textContent = `${diff.toFixed(0)} ms faster (${pct.toFixed(0)}% reduction)`;
                compBarFill.style.width = `${Math.min(100, Math.max(10, pct))}%`;
            } else {
                compDiffVal.textContent = `${Math.abs(diff).toFixed(0)} ms slower`;
                compBarFill.style.width = "0%";
            }
        } else if (currentMode === "optimized" && !lastNaiveT3) {
            compDiffVal.textContent = `Optimized TTFA: ${newT3.toFixed(0)} ms (Switch to Naive to compare)`;
            compBarFill.style.width = "50%";
        } else if (currentMode === "naive" && !lastOptimizedT3) {
            compDiffVal.textContent = `Naive TTFA: ${newT3.toFixed(0)} ms (Switch to Optimized to compare)`;
            compBarFill.style.width = "20%";
        }
    } catch (err) {
        console.error("Error updating comparison HUD:", err);
    }
}

// Push-to-talk Mic Controls
async function startRecording() {
    try {
        if (isPipelineActive || currentAudioElement || isRecording || isStartingRecording) return;
        isStartingRecording = true;
        shouldStopAfterRecordingStarts = false;
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        audioChunks = [];
        const preferredMimeType = "audio/webm;codecs=opus";
        const mimeType = MediaRecorder.isTypeSupported(preferredMimeType)
            ? preferredMimeType
            : "audio/webm";
        mediaRecorder = new MediaRecorder(stream, { mimeType });

        mediaRecorder.ondataavailable = (e) => {
            if (e.data.size > 0) audioChunks.push(e.data);
        };

        mediaRecorder.onstop = async () => {
            try {
                if (audioChunks.length === 0) {
                    throw new Error("No microphone audio was captured. Hold the button while speaking and try again.");
                }
                const audioBlob = new Blob(audioChunks, { type: "audio/webm" });
                const arrayBuffer = await audioBlob.arrayBuffer();

                resetUI();
                t0Val.textContent = "0 ms (Audio Sent)";

                if (ws && ws.readyState === WebSocket.OPEN) {
                    isPipelineActive = true;
                    ws.send(arrayBuffer);
                } else {
                    console.error("WebSocket is not open. Cannot send audio recording.");
                }
            } catch (stopErr) {
                console.error("Error preparing/sending recorded audio:", stopErr);
            }
        };

        mediaRecorder.start();
        isRecording = true;
        isStartingRecording = false;
        micBtn.classList.add("recording");
        micTip.textContent = "Recording... Release button to send";
        if (shouldStopAfterRecordingStarts) stopRecording();
    } catch (err) {
        isStartingRecording = false;
        shouldStopAfterRecordingStarts = false;
        console.error("Microphone access failed:", err);
        alert("Microphone access failed: " + err.message);
    }
}

function stopRecording() {
    try {
        if (isStartingRecording) {
            shouldStopAfterRecordingStarts = true;
            return;
        }
        if (mediaRecorder && isRecording) {
            mediaRecorder.stop();
            mediaRecorder.stream.getTracks().forEach((t) => t.stop());
            isRecording = false;
            micBtn.classList.remove("recording");
            micTip.textContent = "Hold button to speak, or type below";
        }
    } catch (err) {
        console.error("Error stopping recording:", err);
    }
}

micBtn.addEventListener("pointerdown", (e) => { e.preventDefault(); primeAudioPlayback(); startRecording(); });
micBtn.addEventListener("pointerup", (e) => { e.preventDefault(); stopRecording(); });
micBtn.addEventListener("pointercancel", stopRecording);

// Quick Text Submission
function submitTextMessage(text) {
    try {
        const query = text.trim();
        if (!query || isPipelineActive || currentAudioElement) return;

        resetUI();
        userTranscriptEl.textContent = query;
        t0Val.textContent = "0 ms (Prompt Sent)";
        t1Val.textContent = "0 ms (Direct Text)";

        if (ws && ws.readyState === WebSocket.OPEN) {
            isPipelineActive = true;
            ws.send(JSON.stringify({
                action: "text",
                text: query,
                mode: currentMode,
            }));
        } else {
            console.error("WebSocket is not open. Cannot send text query.");
        }
    } catch (err) {
        console.error("Error submitting text message:", err);
    }
}

sendBtn.addEventListener("click", () => {
    primeAudioPlayback();
    submitTextMessage(textInput.value);
    textInput.value = "";
});

textInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
        primeAudioPlayback();
        submitTextMessage(textInput.value);
        textInput.value = "";
    }
});

// Presets
window.selectPreset = function (text) {
    primeAudioPlayback();
    submitTextMessage(text);
};

function resetUI() {
    try {
        stopCurrentAudio();
        receivedAudioChunks = [];
        userTranscriptEl.textContent = "Listening / Transcribing...";
        assistantResponseEl.textContent = "";
        streamingCursor.style.display = "inline-block";
        audioStatusDot.classList.remove("playing");
        audioStatusText.textContent = "Audio idle";
        t0Val.textContent = "—";
        t1Val.textContent = "—";
        t2Val.textContent = "—";
        t3Val.textContent = "—";
    } catch (err) {
        console.error("Error in resetUI:", err);
    }
}

// Bootstrap
window.addEventListener("DOMContentLoaded", () => {
    initWebSocket();
    setMode("optimized");
});
