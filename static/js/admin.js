// Admin Panel Functions

async function loadAdminData() {
    if (!currentUser.is_admin) {
        showNotification('Access denied. Admin privileges required.', 'error');
        switchPage('dashboardPage', null);
        return;
    }
    
    await loadAdminStats();
    await loadAdminUsers();
    await loadAdminFiles();
    await loadBlockedCountries();
}

async function loadAdminStats() {
    try {
        const response = await fetch(`${API_URL}/admin/stats`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        
        const data = await response.json();

        document.getElementById('adminTotalUsers').textContent = data.total_users;
        document.getElementById('adminOnlineUsers').textContent = data.online_users;
        document.getElementById('adminTotalStorage').textContent = formatFileSize(data.total_storage);
        document.getElementById('adminTotalShares').textContent = data.total_shares;
        
        // Update registration toggle
        document.getElementById('regToggle').checked = data.registrations_enabled;
    } catch (error) {
        console.error('Error loading admin stats:', error);
    }
}

async function loadAdminUsers() {
    try {
        const response = await fetch(`${API_URL}/admin/users`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        
        const data = await response.json();
        const usersList = document.getElementById('adminUsersList');

        if (!data.users || data.users.length === 0) {
            usersList.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">👥</div>
                    <p>No users found</p>
                </div>
            `;
            return;
        }

        usersList.innerHTML = '';
        data.users.forEach(user => {
            const lastSeen = user.last_seen ? new Date(user.last_seen) : null;
            const isOnline = lastSeen && (new Date() - lastSeen < 5 * 60 * 1000);
            
            const userItem = document.createElement('div');
            userItem.className = 'file-item';
            
            const userIcon = document.createElement('div');
            userIcon.style.cssText = 'font-size: 24px; width: 48px; height: 48px; display: flex; align-items: center; justify-content: center; background: #f8fafc; border-radius: 12px; border: 1px solid var(--border);';
            userIcon.textContent = '👤';
            
            const userDetails = document.createElement('div');
            userDetails.style.cssText = 'overflow: hidden; flex: 1;';
            
            const userName = document.createElement('div');
            userName.style.cssText = 'font-weight: 700; color: var(--text); font-size: 15px; display: flex; align-items: center; gap: 8px;';
            userName.textContent = user.username;
            
            if (user.is_admin) {
                const adminBadge = document.createElement('span');
                adminBadge.className = 'status-badge success';
                adminBadge.style.fontSize = '10px';
                adminBadge.style.padding = '2px 8px';
                adminBadge.textContent = 'ADMIN';
                userName.appendChild(adminBadge);
            }
            
            if (isOnline) {
                const onlineTag = document.createElement('span');
                onlineTag.style.cssText = 'width: 8px; height: 8px; background: var(--success); border-radius: 50%;';
                onlineTag.title = 'Online';
                userName.appendChild(onlineTag);
            }
            
            if (user.is_blocked) {
                const blockedTag = document.createElement('span');
                blockedTag.className = 'status-badge rejected';
                blockedTag.style.fontSize = '10px';
                blockedTag.style.padding = '2px 8px';
                blockedTag.textContent = 'BLOCKED';
                userName.appendChild(blockedTag);
            }
            
            const userMeta = document.createElement('div');
            userMeta.style.cssText = 'font-size: 12px; color: var(--text-light); margin-top: 4px;';
            userMeta.textContent = `${user.email} • ${user.file_count || 0} files • Joined ${new Date(user.created_at).toLocaleDateString()}`;
            
            userDetails.appendChild(userName);
            userDetails.appendChild(userMeta);
            
            const userActions = document.createElement('div');
            userActions.style.cssText = 'display: flex; gap: 8px;';
            
            if (user.id !== currentUser.id) {
                const blockBtn = document.createElement('button');
                blockBtn.className = 'btn btn-secondary';
                blockBtn.style.cssText = 'padding: 6px 12px; font-size: 11px;';
                blockBtn.textContent = user.is_blocked ? 'Unblock' : 'Block';
                blockBtn.onclick = () => toggleUserBlock(user.id, user.is_blocked);
                
                const deleteBtn = document.createElement('button');
                deleteBtn.className = 'btn btn-danger';
                deleteBtn.style.cssText = 'padding: 6px 12px; font-size: 11px;';
                deleteBtn.textContent = 'Delete';
                deleteBtn.onclick = () => deleteUser(user.id, user.username);
                
                userActions.appendChild(blockBtn);
                userActions.appendChild(deleteBtn);
            } else {
                const currentTag = document.createElement('span');
                currentTag.style.cssText = 'font-size: 12px; color: var(--text-light); font-weight: 600;';
                currentTag.textContent = 'Current User';
                userActions.appendChild(currentTag);
            }
            
            userItem.appendChild(userIcon);
            userItem.appendChild(userDetails);
            userItem.appendChild(userActions);
            usersList.appendChild(userItem);
        });
    } catch (error) {
        console.error('Error loading admin users:', error);
    }
}

async function toggleRegistrations() {
    const enabled = document.getElementById('regToggle').checked;
    try {
        const response = await fetch(`${API_URL}/admin/settings/registrations`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({ enabled })
        });
        
        if (response.ok) {
            showNotification(`Registrations ${enabled ? 'enabled' : 'disabled'} successfully`, 'success');
        } else {
            showNotification('Failed to update registration status', 'error');
            document.getElementById('regToggle').checked = !enabled;
        }
    } catch (error) {
        showNotification('Error updating registration status', 'error');
        document.getElementById('regToggle').checked = !enabled;
    }
}

async function loadBlockedCountries() {
    try {
        const response = await fetch(`${API_URL}/admin/settings/blocked-countries`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        const data = await response.json();
        document.getElementById('blockedCountries').value = data.countries || '';
    } catch (error) {
        console.error('Error loading blocked countries:', error);
    }
}

async function updateBlockedCountries() {
    const countries = document.getElementById('blockedCountries').value;
    try {
        const response = await fetch(`${API_URL}/admin/settings/blocked-countries`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({ countries })
        });
        
        if (response.ok) {
            showNotification('Blocked countries updated successfully', 'success');
        } else {
            showNotification('Failed to update blocked countries', 'error');
        }
    } catch (error) {
        showNotification('Error updating blocked countries', 'error');
    }
}

async function toggleUserBlock(userId, isCurrentlyBlocked) {
    const action = isCurrentlyBlocked ? 'unblock' : 'block';
    if (!confirm(`Are you sure you want to ${action} this user?`)) return;

    try {
        const response = await fetch(`${API_URL}/admin/users/${userId}/block`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({ block: !isCurrentlyBlocked })
        });

        if (response.ok) {
            showNotification(`User ${action}ed successfully`, 'success');
            loadAdminUsers();
        } else {
            const data = await response.json();
            showNotification(data.message || `Failed to ${action} user`, 'error');
        }
    } catch (error) {
        showNotification(`Error ${action}ing user`, 'error');
    }
}

async function loadAdminFiles() {
    try {
        const response = await fetch(`${API_URL}/admin/files`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        
        const data = await response.json();
        const filesBody = document.getElementById('adminFilesBody');

        if (!data.files || data.files.length === 0) {
            filesBody.innerHTML = `
                <tr>
                    <td colspan="5" style="text-align: center; padding: 48px; color: var(--text-light);">
                        <div style="font-size: 48px; margin-bottom: 16px; opacity: 0.2;">📂</div>
                        No files found on the platform
                    </td>
                </tr>
            `;
            return;
        }

        filesBody.innerHTML = data.files.map(file => `
            <tr>
                <td style="font-weight: 600;">${file.filename}</td>
                <td><span class="status-badge" style="background: #f1f5f9; color: var(--text); font-size: 11px;">${file.username}</span></td>
                <td>${formatFileSize(file.size)}</td>
                <td style="color: var(--text-light); font-size: 13px;">${new Date(file.uploaded_at).toLocaleDateString()}</td>
                <td>
                    <div style="display: flex; gap: 8px;">
                        <button class="btn btn-secondary" style="padding: 6px 12px; font-size: 11px;" 
                            onclick="openPreviewModal(${file.id}, '${file.filename.replace(/'/g, "\\'")}', '${file.type}', '${file.hls_path || ''}')">Preview</button>
                        <button class="btn btn-danger" style="padding: 6px 12px; font-size: 11px;" 
                            onclick="adminDeleteFile(${file.id}, '${file.filename.replace(/'/g, "\\'")}')">Delete</button>
                    </div>
                </td>
            </tr>
        `).join('');
    } catch (error) {
        console.error('Error loading admin files:', error);
    }
}

async function toggleAdminStatus(userId, isCurrentlyAdmin) {
    const action = isCurrentlyAdmin ? 'remove admin privileges from' : 'grant admin privileges to';
    if (!confirm(`Are you sure you want to ${action} this user?`)) return;

    try {
        const response = await fetch(`${API_URL}/admin/users/${userId}/toggle-admin`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` }
        });

        if (response.ok) {
            showNotification('Admin status updated successfully', 'success');
            loadAdminUsers();
        } else {
            const data = await response.json();
            showNotification(data.message || 'Failed to update admin status', 'error');
        }
    } catch (error) {
        showNotification('Error updating admin status', 'error');
    }
}

async function deleteUser(userId, username) {
    if (!confirm(`Are you sure you want to delete user "${username}"? This will also delete all their files and shares.`)) return;

    try {
        const response = await fetch(`${API_URL}/admin/users/${userId}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${token}` }
        });

        if (response.ok) {
            showNotification('User deleted successfully', 'success');
            loadAdminData();
        } else {
            const data = await response.json();
            showNotification(data.message || 'Failed to delete user', 'error');
        }
    } catch (error) {
        showNotification('Error deleting user', 'error');
    }
}

async function adminDeleteFile(fileId, filename) {
    if (!confirm(`Are you sure you want to delete "${filename}"?`)) return;

    try {
        const response = await fetch(`${API_URL}/admin/files/${fileId}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${token}` }
        });

        if (response.ok) {
            showNotification('File deleted successfully', 'success');
            loadAdminData();
        } else {
            const data = await response.json();
            showNotification(data.message || 'Failed to delete file', 'error');
        }
    } catch (error) {
        showNotification('Error deleting file', 'error');
    }
}

function openAddUserModal() {
    document.getElementById('addUserModal').classList.add('active');
}

function closeAddUserModal() {
    document.getElementById('addUserModal').classList.remove('active');
    document.getElementById('addUserName').value = '';
    document.getElementById('addUserEmail').value = '';
    document.getElementById('addUserPassword').value = '';
    document.getElementById('addUserIsAdmin').checked = false;
}

async function handleAddUser() {
    const username = document.getElementById('addUserName').value;
    const email = document.getElementById('addUserEmail').value;
    const password = document.getElementById('addUserPassword').value;
    const isAdmin = document.getElementById('addUserIsAdmin').checked;

    if (!username || !email || !password) {
        showNotification('Please fill all required fields', 'error');
        return;
    }

    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email)) {
        showNotification('Please enter a valid email address', 'error');
        return;
    }

    if (password.length < 6) {
        showNotification('Password must be at least 6 characters', 'error');
        return;
    }

    try {
        const response = await fetch(`${API_URL}/admin/users/create`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
            body: JSON.stringify({
                username,
                email,
                password,
                is_admin: isAdmin
            })
        });

        const data = await response.json();

        if (response.ok) {
            showNotification(`User "${username}" created successfully!`, 'success');
            closeAddUserModal();
            loadAdminUsers();
        } else {
            showNotification(data.message || 'Failed to create user', 'error');
        }
    } catch (error) {
        showNotification('Error creating user', 'error');
    }
}
