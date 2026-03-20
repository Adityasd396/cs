// Statistics and Settings Functions

async function loadStats() {
    try {
        const response = await fetch(`${API_URL}/user/stats`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        
        const data = await response.json();

        // Update dashboard stats
        const updateText = (id, text) => {
            const el = document.getElementById(id);
            if (el) el.textContent = text;
        };

        updateText('userBalance', `₹${data.balance.toFixed(2)}`);
        updateText('totalEarned', `₹${data.total_earned.toFixed(2)}`);
        updateText('avgCpm', `₹${data.avg_cpm.toFixed(2)}`);
        updateText('totalViews', data.total_views);
        updateText('totalFiles', data.total_files);
        updateText('storageUsed', data.storage_used);

        // Update detailed views
        updateText('viewsToday', data.views_today);
        updateText('viewsYesterday', data.views_yesterday);
        updateText('views7Days', data.views_7days);
        updateText('viewsMonth', data.views_month);

        // Render recent activity
        const activityList = document.getElementById('recentActivityList');
        if (activityList && data.recent_activity) {
            if (data.recent_activity.length === 0) {
                activityList.innerHTML = '<div class="empty-state">No recent activity</div>';
            } else {
                activityList.innerHTML = data.recent_activity.map(a => `
                    <div class="file-item">
                        <div class="file-info">
                            <div style="font-weight: 600; color: #1e293b;">${a.filename}</div>
                            <div class="file-meta">Viewed from ${a.ip} at ${new Date(a.time).toLocaleString()}</div>
                        </div>
                        <div style="font-weight: 800; color: var(--success); font-size: 14px;">+₹${a.earned.toFixed(4)}</div>
                    </div>
                `).join('');
            }
        }
    } catch (error) {
        console.error('Error loading stats:', error);
    }
}

async function loadSettings() {
    document.getElementById('settingUsername').textContent = currentUser.username || '-';
    document.getElementById('settingEmail').textContent = currentUser.email || '-';
    if (document.getElementById('userName')) {
        document.getElementById('userName').textContent = currentUser.username || 'User';
    }
    
    // Set saved UPI if available
    if (currentUser.upi_number && document.getElementById('upiNumber')) {
        document.getElementById('upiNumber').value = currentUser.upi_number;
    }

    try {
        const response = await fetch(`${API_URL}/user/stats`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        
        const data = await response.json();

        document.getElementById('settingTotalFiles').textContent = data.total_files;
        document.getElementById('settingStorageUsed').textContent = data.storage_used;
        
        if (document.getElementById('settingsBalance')) {
            document.getElementById('settingsBalance').textContent = `₹${data.balance.toFixed(2)}`;
        }
        
        loadPaymentHistory();
    } catch (error) {
        console.error('Error loading settings:', error);
    }
}

async function saveUPI() {
    const upiNo = document.getElementById('upiNumber').value;
    if (!upiNo || upiNo.length !== 10 || !/^\d+$/.test(upiNo)) {
        showNotification('Please enter a valid 10-digit UPI number', 'error');
        return;
    }

    try {
        const response = await fetch(`${API_URL}/user/update-upi`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ upi_no: upiNo })
        });
        const data = await response.json();
        if (response.ok) {
            showNotification(data.message, 'success');
            // Update local storage user data
            currentUser.upi_number = upiNo;
            localStorage.setItem('user', JSON.stringify(currentUser));
        } else {
            showNotification(data.message || 'Save failed', 'error');
        }
    } catch (error) {
        showNotification('An error occurred', 'error');
    }
}

async function requestPayment() {
    const upiNo = document.getElementById('upiNumber').value;
    
    if (!upiNo || upiNo.length !== 10 || !/^\d+$/.test(upiNo)) {
        showNotification('Please enter a valid 10-digit UPI number', 'error');
        return;
    }

    const btn = document.getElementById('requestPaymentBtn');
    btn.disabled = true;
    btn.textContent = 'Processing...';

    try {
        const response = await fetch(`${API_URL}/user/request-payment`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ upi_no: upiNo })
        });
        const data = await response.json();
        
        if (response.ok) {
            showNotification(data.message, 'success');
            document.getElementById('upiNumber').value = '';
            loadSettings();
            loadStats();
        } else {
            showNotification(data.message || 'Request failed', 'error');
        }
    } catch (error) {
        showNotification('An error occurred', 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Request Payment';
    }
}

async function loadPaymentHistory() {
    const list = document.getElementById('paymentHistoryList');
    if (!list) return;

    try {
        const response = await fetch(`${API_URL}/user/payments`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        const data = await response.json();
        
        if (data.payments && data.payments.length > 0) {
            list.innerHTML = data.payments.map(p => `
                <div class="setting-row" style="padding: 10px 0; border-bottom: 1px solid var(--border);">
                    <div>
                        <div style="font-weight: 600;">₹${p.amount.toFixed(2)}</div>
                        <div style="font-size: 11px; color: var(--text-light);">UPI: ${p.payment_info}</div>
                        <div style="font-size: 10px; color: #94a3b8;">${new Date(p.created_at).toLocaleString()}</div>
                    </div>
                    <div class="status-badge ${p.status}">${p.status.toUpperCase()}</div>
                </div>
            `).join('');
        } else {
            list.innerHTML = '<div class="empty-state" style="padding: 20px;">No payment history</div>';
        }
    } catch (error) {
        console.error('Error loading payments:', error);
    }
}
