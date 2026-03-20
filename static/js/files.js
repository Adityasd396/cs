// File Management Functions

function setupUploadArea() {
    const uploadArea = document.getElementById('uploadArea');
    const fileInput = document.getElementById('fileInput');
    
    uploadArea.addEventListener('click', () => fileInput.click());
    
    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.classList.add('drag');
    });
    
    uploadArea.addEventListener('dragleave', () => {
        uploadArea.classList.remove('drag');
    });
    
    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('drag');
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            fileInput.files = files;
            handleFileSelect({ target: { files: files } });
        }
    });
}

function handleFileSelect(event) {
    const files = event.target.files;
    if (files.length > 0) {
        const uploadBtn = document.getElementById('uploadBtn');
        const uploadText = document.querySelector('.upload-text');
        
        uploadBtn.style.display = 'block';
        if (files.length === 1) {
            uploadText.innerHTML = `Selected: <strong>${files[0].name}</strong> (${formatFileSize(files[0].size)})`;
        } else {
            uploadText.innerHTML = `Selected: <strong>${files.length} files</strong>`;
        }
    }
}

async function uploadFile() {
    const fileInput = document.getElementById('fileInput');
    if (!fileInput.files.length) {
        showNotification('Please select at least one file', 'error');
        return;
    }

    const files = Array.from(fileInput.files);
    const uploadBtn = document.getElementById('uploadBtn');
    const progressContainer = document.getElementById('progressContainer');
    const progressFill = document.getElementById('progressFill');
    const progressText = document.getElementById('progressText');
    const uploadText = document.querySelector('.upload-text');

    uploadBtn.disabled = true;
    uploadBtn.textContent = 'Uploading...';
    progressContainer.style.display = 'block';
    uploadText.style.display = 'none';

    let successCount = 0;
    let failCount = 0;

    for (let i = 0; i < files.length; i++) {
        const file = files[i];
        const formData = new FormData();
        formData.append('file', file);
        if (currentFolderId) formData.append('folder_id', currentFolderId);

        try {
            await new Promise((resolve, reject) => {
                const xhr = new XMLHttpRequest();
                
                xhr.upload.addEventListener('progress', (e) => {
                    if (e.lengthComputable) {
                        const percent = Math.round((e.loaded / e.total) * 100);
                        progressFill.style.width = percent + '%';
                        progressText.textContent = `Uploading ${i + 1}/${files.length}: ${percent}%`;
                        
                        if (percent === 100) {
                            progressText.textContent = `Processing ${i + 1}/${files.length}: Encrypting and saving...`;
                        }
                    }
                });

                xhr.addEventListener('load', () => {
                    if (xhr.status === 201 || xhr.status === 200) {
                        successCount++;
                        resolve();
                    } else {
                        reject(new Error('Upload failed'));
                    }
                });

                xhr.addEventListener('error', () => reject(new Error('Network error')));
                xhr.open('POST', `${API_URL}/files/upload`);
                xhr.setRequestHeader('Authorization', `Bearer ${token}`);
                xhr.send(formData);
            });
        } catch (error) {
            console.error(error);
            failCount++;
        }
    }

    // Completion UI logic
    progressContainer.style.display = 'none';
    progressFill.style.width = '0%';
    uploadBtn.disabled = false;
    uploadBtn.style.display = 'none';
    uploadBtn.textContent = 'Upload File';
    fileInput.value = '';
    
    uploadText.style.display = 'block';
    uploadText.innerHTML = 'Drag and drop or <strong>click to browse</strong>';

    if (successCount > 0) {
        showNotification(`Successfully uploaded ${successCount} file(s)${failCount > 0 ? `. ${failCount} failed.` : ''}`, 'success');
        loadFiles();
        loadStats();
    } else if (failCount > 0) {
        showNotification('Upload failed. Check server logs or try smaller files.', 'error');
    }
}

async function loadFiles() {
    try {
        const response = await fetch(`${API_URL}/files?folder_id=${currentFolderId || ''}`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        
        const data = await response.json();
        allFiles = data.files || [];
        
        renderFiles();
    } catch (error) {
        console.error('Error loading files:', error);
    }
}

function renderFiles() {
    const filesList = document.getElementById('filesList');
    const filteredFiles = filterFilesByType(allFiles);

    if (filteredFiles.length === 0) {
        filesList.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">📁</div>
                <p>${allFiles.length === 0 ? 'No files yet. Upload your first file!' : 'No files match the current filter.'}</p>
            </div>
        `;
        return;
    }

    filesList.innerHTML = filteredFiles.map(file => {
        const fileIcon = getFileIcon(file.filename);
        const uploadDate = new Date(file.uploaded_at).toLocaleDateString();
        
        return `
            <div class="file-item" data-filename="${file.filename.toLowerCase()}" data-type="${getFileType(file.filename)}">
                <div style="display: flex; align-items: center; gap: 16px; flex: 1;">
                    <div style="font-size: 28px; width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; background: #f8fafc; border-radius: 12px; border: 1px solid var(--border);">${fileIcon}</div>
                    <div style="overflow: hidden;">
                        <div style="font-weight: 700; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 15px;" title="${file.filename}">${file.filename}</div>
                        <div style="font-size: 12px; color: var(--text-light); margin-top: 4px; display: flex; align-items: center; gap: 8px;">
                            <span>${formatFileSize(file.size)}</span>
                            <span style="opacity: 0.5;">•</span>
                            <span>${uploadDate}</span>
                            <span style="opacity: 0.5;">•</span>
                            <span style="color: var(--primary); font-weight: 600;">${file.total_views || 0} views</span>
                        </div>
                    </div>
                </div>
                <div style="display: flex; gap: 8px;">
                    <button class="btn btn-secondary" style="padding: 8px 12px; font-size: 12px;" onclick="openPreviewModal(${file.id}, '${file.filename.replace(/'/g, "\\'")}', '${file.type}', '${file.hls_path || ''}')">
                        Preview
                    </button>
                    <button class="btn btn-primary" style="padding: 8px 12px; font-size: 12px;" onclick="autoShareFile(${file.id})">
                        Share
                    </button>
                    <button class="btn btn-secondary" style="padding: 8px 12px; font-size: 12px;" onclick="downloadFile(${file.id}, '${file.filename.replace(/'/g, "\\'")}')">
                        Download
                    </button>
                    <button class="btn btn-danger" style="padding: 8px 12px; font-size: 12px;" onclick="deleteFile(${file.id}, '${file.filename.replace(/'/g, "\\'")}')">
                        Delete
                    </button>
                </div>
            </div>
        `;
    }).join('');
}

function filterFilesByType(files) {
    if (currentFileTypeFilter === 'all') {
        return files;
    }
    return files.filter(file => getFileType(file.filename) === currentFileTypeFilter);
}

function filterByType(type) {
    currentFileTypeFilter = type;
    
    // Update active tab
    document.querySelectorAll('.file-type-tab').forEach(tab => {
        tab.classList.remove('active');
    });
    event.target.classList.add('active');
    
    renderFiles();
}

function filterFiles() {
    const query = document.getElementById('searchInput').value.toLowerCase();
    const items = document.querySelectorAll('.file-item');
    
    items.forEach(item => {
        const filename = item.dataset.filename;
        item.style.display = filename.includes(query) ? 'flex' : 'none';
    });
}

async function downloadFile(fileId, filename) {
    try {
        const response = await fetch(`${API_URL}/files/${fileId}`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });

        if (!response.ok) {
            showNotification('Download failed', 'error');
            return;
        }

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
        showNotification('Download started', 'success');
    } catch (error) {
        showNotification('Download error', 'error');
    }
}

async function deleteFile(fileId, filename) {
    if (!confirm(`Are you sure you want to delete "${filename}"?`)) {
        return;
    }

    try {
        const response = await fetch(`${API_URL}/files/${fileId}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${token}` }
        });

        if (response.ok) {
            showNotification('File deleted successfully', 'success');
            loadFiles();
            loadStats();
        } else {
            const data = await response.json();
            showNotification(data.message || 'Delete failed', 'error');
        }
    } catch (error) {
        showNotification('Delete error', 'error');
    }
}

function openPreviewModal(fileId, filename, mimeType, hlsPath) {
    const modal = document.getElementById('previewModal');
    const previewTitle = document.getElementById('previewTitle');
    const previewContent = document.getElementById('previewContent');
    
    modal.classList.add('active');
    previewTitle.textContent = filename;
    
    const fileType = getFileType(filename);
    const fileUrl = `${API_URL}/files/${fileId}?preview=true`;
    
    // Create temporary token for preview (using existing auth)
    const authHeader = `Bearer ${token}`;
    
    if (fileType === 'image') {
        previewContent.innerHTML = `
            <div style="text-align: center;">
                <img id="previewImage" src="" 
                     style="max-width: 100%; max-height: 500px; object-fit: contain; display: none;" 
                     alt="${filename}">
                <div id="imageLoader">Loading image...</div>
            </div>
        `;
        
        fetch(fileUrl, {
            headers: { 'Authorization': authHeader }
        })
        .then(response => {
            if (!response.ok) throw new Error('Image not found');
            return response.blob();
        })
        .then(blob => {
            const imgUrl = URL.createObjectURL(blob);
            const img = document.getElementById('previewImage');
            const loader = document.getElementById('imageLoader');
            img.onload = function() {
                loader.style.display = 'none';
                img.style.display = 'block';
            };
            img.src = imgUrl;
        })
        .catch(err => {
            previewContent.innerHTML = `
                <div style="text-align: center; padding: 40px; color: var(--text-light);">
                    <div style="font-size: 48px; margin-bottom: 16px;">⚠️</div>
                    <p>Failed to load image</p>
                </div>
            `;
        });
    } else if (fileType === 'video') {
        // PRIORITY: Always use HLS if available for perfect seeking
        if (hlsPath) {
            const hlsUrl = `${window.location.origin}/hls/${hlsPath}`;
            previewContent.innerHTML = `
                <div style="text-align: center; background: #000; border-radius: 8px; overflow: hidden; position: relative;">
                    <video id="previewVideo" controls autoplay playsinline style="max-width: 100%; max-height: 500px; width: 100%;"></video>
                    <div id="videoBadge" style="position: absolute; top: 10px; right: 10px; background: rgba(0,0,0,0.5); color: #fff; padding: 4px 8px; border-radius: 4px; font-size: 10px; pointer-events: none;">HLS STREAMING</div>
                </div>
            `;
            
            const video = document.getElementById('previewVideo');
            
            // Native HLS support (Safari)
            if (video.canPlayType('application/vnd.apple.mpegurl')) {
                video.src = hlsUrl;
            } else if (typeof Hls !== 'undefined' && Hls.isSupported()) {
                // Hls.js support (Chrome/Firefox)
                const hls = new Hls({
                    enableWorker: true,
                    lowLatencyMode: false, // Better for VOD seeking
                    backBufferLength: 90,
                    maxBufferLength: 60,
                    maxMaxBufferLength: 120,
                    appendErrorMaxRetry: 5,
                    startLevel: -1,
                    capLevelToPlayerSize: true
                });
                hls.loadSource(hlsUrl);
                hls.attachMedia(video);
                hls.on(Hls.Events.MANIFEST_PARSED, function() {
                    video.play();
                });

                hls.on(Hls.Events.ERROR, function (event, data) {
                    if (data.fatal) {
                        switch (data.type) {
                            case Hls.ErrorTypes.NETWORK_ERROR:
                                hls.startLoad();
                                break;
                            case Hls.ErrorTypes.MEDIA_ERROR:
                                hls.recoverMediaError();
                                break;
                            default:
                                hls.destroy();
                                break;
                        }
                    }
                });
                
                // Handle cleanup
                modal.onclick = function(e) {
                    if (e.target === modal) {
                        hls.destroy();
                        closePreviewModal();
                    }
                };
            }
        } else if (fileType === 'video') {
            // Video is still being converted to HLS (Processing state)
            previewContent.innerHTML = `
                <div style="text-align: center; padding: 60px; background: #f8fafc; border-radius: 12px; border: 2px dashed var(--border);">
                    <div class="loading-spinner" style="margin: 0 auto 20px;"></div>
                    <h3 style="margin-bottom: 10px; color: var(--text);">Video is Processing...</h3>
                    <p style="color: var(--text-light); max-width: 300px; margin: 0 auto;">We are preparing this video for high-speed seeking. Please wait 1-2 minutes and refresh.</p>
                    <button class="btn btn-primary" style="margin-top: 20px;" onclick="location.reload()">Refresh Page</button>
                </div>
            `;
        } else {
            // Fallback to direct video file streaming (unlikely for videos now)
            previewContent.innerHTML = `
                <div style="text-align: center; background: #000; border-radius: 8px; overflow: hidden;">
                    <video id="previewVideo" controls autoplay playsinline style="max-width: 100%; max-height: 500px; width: 100%;">
                        <source src="${fileUrl}" type="${mimeType || 'video/mp4'}">
                        Your browser does not support video playback.
                    </video>
                </div>
            `;
        }
    } else if (fileType === 'audio') {
        // Use direct URL for audio streaming (HttpOnly cookie will handle auth)
        previewContent.innerHTML = `
            <div style="text-align: center; padding: 40px; background: #f8f9fa; border-radius: 8px;">
                <div style="font-size: 48px; margin-bottom: 16px;">🎵</div>
                <audio id="previewAudio" controls autoplay style="width: 100%; max-width: 500px;">
                    <source src="${fileUrl}" type="${mimeType || 'audio/mpeg'}">
                    Your browser does not support audio playback.
                </audio>
            </div>
        `;
    } else if (fileType === 'document' && filename.toLowerCase().endsWith('.txt')) {
        previewContent.innerHTML = `<div id="textLoader" style="text-align: center; padding: 40px;">Loading text...</div>`;
        
        fetch(fileUrl, {
            headers: { 'Authorization': authHeader }
        })
        .then(response => response.text())
        .then(text => {
            previewContent.innerHTML = `
                <div style="background: var(--bg); padding: 20px; border-radius: 8px; max-height: 500px; overflow-y: auto; text-align: left;">
                    <pre style="white-space: pre-wrap; word-wrap: break-word; font-family: monospace; font-size: 13px; margin: 0;">${text}</pre>
                </div>
            `;
        })
        .catch(err => {
            previewContent.innerHTML = `
                <div style="text-align: center; padding: 40px; color: var(--text-light);">
                    <div style="font-size: 48px; margin-bottom: 16px;">⚠️</div>
                    <p>Failed to load text file</p>
                </div>
            `;
        });
    } else {
        previewContent.innerHTML = `
            <div style="text-align: center; padding: 40px; color: var(--text-light);">
                <div style="font-size: 48px; margin-bottom: 16px;">${getFileIcon(filename)}</div>
                <p>Preview not available for this file type.</p>
                <p style="margin-top: 8px; font-size: 14px;">Click download to view the file.</p>
                <button class="btn btn-primary" style="margin-top: 20px; width: auto;" 
                        onclick="closePreviewModal(); downloadFile(${fileId}, '${filename.replace(/'/g, "\\'")}')">
                    Download File
                </button>
            </div>
        `;
    }
}

function closePreviewModal() {
    document.getElementById('previewModal').classList.remove('active');
}