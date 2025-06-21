let currentVideoInfo = null;
let abortController = null;

async function fetchVideoInfo() {
    const input = document.getElementById("videoURL");
    const url = input.value.trim();
    const fetchBtn = document.querySelector("button");
    
    // Get UI elements
    const videoInfoDiv = document.getElementById("videoInfo");
    const videoThumbnail = document.getElementById("videoThumbnail");
    const videoTitle = document.getElementById("videoTitle");
    const videoDuration = document.getElementById("videoDuration");
    const downloadOptionsDiv = document.getElementById("downloadOptions");

    if (!url) {
        alert("Please enter a YouTube URL.");
        return;
    }

    // Reset UI
    videoInfoDiv.style.display = "none";
    downloadOptionsDiv.style.display = "none";
    fetchBtn.disabled = true;
    fetchBtn.textContent = "Checking...";

    try {
        const response = await fetch("/check", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ url: url })
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || "Failed to fetch video info");
        }

        const data = await response.json();
        currentVideoInfo = data;

        // Update UI
        videoTitle.textContent = data.title;
        const minutes = Math.floor(data.length / 60);
        const seconds = data.length % 60;
        videoDuration.textContent = `${minutes}:${seconds < 10 ? '0' : ''}${seconds}`;
        videoThumbnail.src = data.thumbnail;
        
        videoInfoDiv.style.display = "block";
        downloadOptionsDiv.style.display = "block";
        
    } catch (error) {
        console.error("Fetch error:", error);
        alert(`Error: ${error.message}`);
    } finally {
        fetchBtn.disabled = false;
        fetchBtn.textContent = "Fetch Video Info";
    }
}

async function downloadVideo(format) {
    if (!currentVideoInfo) {
        alert("Please fetch video info first.");
        return;
    }

    const url = document.getElementById("videoURL").value.trim();
    const quality = document.getElementById("videoQuality").value;
    const bitrate = document.getElementById("audioBitrate").value;

    const btn = event.target;
    const progressDiv = document.getElementById("downloadProgress");
    const progressBar = progressDiv.querySelector("progress");
    const progressText = document.getElementById("progressText");

    abortController = new AbortController(); // reset controller for new download

    btn.disabled = true;
    progressDiv.style.display = "block";
    progressBar.value = 0;
    progressText.textContent = "Preparing download...";

    try {
        const response = await fetch("/download", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            signal: abortController.signal,
            body: JSON.stringify({
                url,
                format,
                quality: format === "video" ? quality : undefined,
                bitrate: format === "audio" ? bitrate : undefined
            })
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || "Download failed");
        }

        const contentLength = parseInt(response.headers.get('Content-Length')) || 0;
        let receivedLength = 0;
        const reader = response.body.getReader();
        const chunks = [];

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            chunks.push(value);
            receivedLength += value.length;

            if (contentLength > 0) {
                const percent = Math.round((receivedLength / contentLength) * 100);
                progressBar.value = percent;
                progressText.textContent = `Downloading... ${percent}%`;
            }
        }

        const blob = new Blob(chunks);
        const blobUrl = URL.createObjectURL(blob);

        const a = document.createElement("a");
        a.href = blobUrl;
        a.download = `${currentVideoInfo.title.replace(/[^\w\s.-]/g, '')}.${format === "audio" ? "mp3" : "mp4"}`;
        document.body.appendChild(a);
        a.click();

        setTimeout(() => {
            document.body.removeChild(a);
            URL.revokeObjectURL(blobUrl);
        }, 100);

        progressText.textContent = "Download complete.";
    } catch (error) {
        if (error.name === 'AbortError') {
            console.log("Download aborted");
            progressText.textContent = "Download cancelled";
        } else {
            console.error("Download error:", error);
            progressText.textContent = `Error: ${error.message}`;
            alert(`Download failed: ${error.message}`);
        }
    } finally {
        btn.disabled = false;
        abortController = null;
    }
}


// Add cancel download functionality
function cancelDownload() {
    if (abortController) {
        abortController.abort();
    }
}

// Add event listener for page unload to cancel ongoing downloads
window.addEventListener('beforeunload', () => {
    if (abortController) {
        abortController.abort();
    }
});