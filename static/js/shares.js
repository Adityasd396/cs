// File Sharing Functions

async function autoShareFile(fileId) {
    try {
        const response = await fetch(`${API_URL}/shares/create`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({
                file_id: fileId
            })
        });

        const data = await response.json();

        if (response.ok) {
            copyToClipboard(data.share.url);
            showNotification('Share link copied to clipboard!', 'success');
            loadShares();
            loadStats();
        } else {
            showNotification(data.message || 'Failed to create share link', 'error');
        }
    } catch (error) {
        console.error('Auto-share error:', error);
        showNotification('Failed to create share link: ' + error.message, 'error');
    }
}

function openShareModal(fileId) {
    selectedFileId = fileId;
    document.getElementById('shareModal').classList.add('active');
}

function closeModal() {
    document.getElementById('shareModal').classList.remove('active');
    document.getElementById('sharePassword').value = '';
    document.getElementById('shareExpiry').value = '24';
}

async function createShare() {
    const password = document.getElementById('sharePassword').value;
    const expiry_hours = parseInt(document.getElementById('shareExpiry').value);

    if (expiry_hours < 1) {
        showNotification('Expiry must be at least 1 hour', 'error');
        return;
    }

    if (!selectedFileId) {
        showNotification('No file selected', 'error');
        return;
    }

    try {
        const response = await fetch(`${API_URL}/shares/create`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({
                file_id: selectedFileId,
                password,
                expiry_hours
            })
        });

        const data = await response.json();

        if (response.ok) {
            showNotification('Share link created successfully!', 'success');
            closeModal();
            loadShares();
            loadStats();
        } else {
            showNotification(data.message || 'Failed to create share link', 'error');
        }
    } catch (error) {
        console.error('Share creation error:', error);
        showNotification('Failed to create share link: ' + error.message, 'error');
    }
}

async function loadShares() {
    try {
        const response = await fetch(`${API_URL}/shares`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        
        const data = await response.json();
        const sharesList = document.getElementById('sharesList');

        if (!data.shares || data.shares.length === 0) {
            sharesList.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">🔗</div>
                    <p>No shared links yet. Create one from the Files tab!</p>
                </div>
            `;
            return;
        }

        sharesList.innerHTML = data.shares.map(share => {
            const expiresDate = new Date(share.expires_at);
            const now = new Date();
            const isExpired = expiresDate < now;
            
            return `
                <div class="file-item">
                    <div style="display: flex; align-items: center; gap: 16px; flex: 1;">
                        <div style="font-size: 24px;">🔗</div>
                        <div style="overflow: hidden;">
                            <div style="font-weight: 700; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${share.filename}">${share.filename}</div>
                            <div style="font-size: 12px; color: var(--text-light); margin-top: 4px;">
                                Views: <span style="font-weight: 600; color: var(--primary);">${share.access_count}</span> • 
                                <span style="color: ${isExpired ? 'var(--error)' : 'inherit'};">
                                    ${isExpired ? 'Expired' : 'Expires: ' + expiresDate.toLocaleString()}
                                </span>
                            </div>
                        </div>
                    </div>
                    <div style="display: flex; gap: 8px;">
                        <button class="btn btn-secondary" style="padding: 8px 16px; font-size: 12px;" onclick="copyToClipboard('${share.url}')">
                            Copy Link
                        </button>
                        <button class="btn btn-danger" style="padding: 8px 16px; font-size: 12px;" onclick="deleteShare('${share.id}')">
                            Delete
                        </button>
                    </div>
                </div>
            `;
        }).join('');
    } catch (error) {
        console.error('Error loading shares:', error);
    }
}

async function deleteShare(shareId) {
    if (!confirm('Are you sure you want to delete this share link?')) {
        return;
    }

    try {
        const response = await fetch(`${API_URL}/shares/${shareId}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${token}` }
        });

        const data = await response.json();

        if (response.ok) {
            showNotification('Share deleted successfully', 'success');
            loadShares();
            loadStats();
        } else {
            showNotification(data.message || 'Failed to delete share', 'error');
        }
    } catch (error) {
        showNotification('Error deleting share', 'error');
    }
}