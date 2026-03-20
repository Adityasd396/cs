// Authentication Functions

// Use global API_URL if defined, otherwise default to /api
if (typeof API_URL === 'undefined') {
    window.API_URL = '/api';
}

// Mobile Navigation Toggle
function toggleMobileNav() {
    const nav = document.getElementById('mobileNav');
    if (nav) {
        nav.style.display = (nav.style.display === 'flex' || nav.style.display === '') ? 'none' : 'flex';
    }
}

// Inject Mobile Menu for Landing Page if missing
document.addEventListener('DOMContentLoaded', () => {
    const isLandingPage = document.querySelector('.hero') !== null;
    if (isLandingPage && !document.getElementById('mobileNav')) {
        const header = document.querySelector('.header-landing') || document.querySelector('header');
        if (header) {
            // Add hamburger button if missing
            if (!document.querySelector('.mobile-menu-btn')) {
                const btn = document.createElement('button');
                btn.className = 'mobile-menu-btn';
                btn.innerHTML = '☰';
                btn.onclick = toggleMobileNav;
                header.querySelector('.container').appendChild(btn);
            }

            // Create mobile nav overlay
            const mobileNav = document.createElement('div');
            mobileNav.id = 'mobileNav';
            mobileNav.innerHTML = `
                <a href="#how-it-works" onclick="toggleMobileNav()">How It Works</a>
                <a href="#features" onclick="toggleMobileNav()">Features</a>
                <a href="#earnings" onclick="toggleMobileNav()">Earnings</a>
                <hr style="border:0;border-top:1px solid rgba(255,255,255,0.1);margin:8px 0;">
                <button class="btn-outline-white" onclick="openModal('login');toggleMobileNav()" style="width:100%;">Login</button>
                <button class="btn btn-primary" onclick="openModal('signup');toggleMobileNav()" style="width:100%;margin-top:10px;">Start Earning</button>
            `;
            header.appendChild(mobileNav);
        }
    }
});

async function handleLogin() {
    const email = document.getElementById('loginEmail').value;
    const password = document.getElementById('loginPassword').value;
    
    if (!email || !password) {
        showNotification('Please fill all fields', 'error');
        return;
    }
    
    try {
        const response = await fetch(`${API_URL}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password })
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            showNotification(data.message, 'error');
            return;
        }
        
        localStorage.setItem('token', data.token);
        localStorage.setItem('user', JSON.stringify(data.user));
        
        showNotification('Login successful!', 'success');
        setTimeout(() => {
            window.location.href = '/dashboard.html';
        }, 500);
    } catch (error) {
        showNotification('Login failed. Please try again.', 'error');
    }
}

async function handleSignup() {
    const username = document.getElementById('signupUsername').value;
    const email = document.getElementById('signupEmail').value;
    const password = document.getElementById('signupPassword').value;
    const confirm = document.getElementById('signupConfirm').value;

    if (!username || !email || !password || !confirm) {
        showNotification('Please fill all fields', 'error');
        return;
    }
    
    if (password !== confirm) {
        showNotification('Passwords do not match', 'error');
        return;
    }
    
    if (password.length < 6) {
        showNotification('Password must be at least 6 characters', 'error');
        return;
    }

    try {
        const response = await fetch(`${API_URL}/auth/signup`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, email, password })
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            showNotification(data.message, 'error');
            return;
        }
        
        showNotification('Account created! Please login.', 'success');
        if (typeof switchAuthPage === 'function') {
            setTimeout(() => switchAuthPage('loginPage'), 1000);
        } else {
            setTimeout(() => window.location.reload(), 1000);
        }
    } catch (error) {
        showNotification('Signup failed. Please try again.', 'error');
    }
}

async function handleLogout() {
    if (confirm('Are you sure you want to logout?')) {
        try {
            const token = localStorage.getItem('token');
            await fetch(`${API_URL}/auth/logout`, { 
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` }
            });
        } catch (e) {}
        
        localStorage.removeItem('token');
        localStorage.removeItem('user');
        window.location.href = '/index.html';
    }
}

function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    notification.textContent = message;
    document.body.appendChild(notification);
    
    // Simple styling if not in CSS
    notification.style.position = 'fixed';
    notification.style.top = '20px';
    notification.style.right = '20px';
    notification.style.padding = '15px 25px';
    notification.style.borderRadius = '8px';
    notification.style.color = 'white';
    notification.style.zIndex = '9999';
    notification.style.transition = 'all 0.3s ease';
    notification.style.opacity = '0';
    
    if (type === 'success') notification.style.backgroundColor = '#10b981';
    else if (type === 'error') notification.style.backgroundColor = '#ef4444';
    else notification.style.backgroundColor = '#3b82f6';
    
    setTimeout(() => {
        notification.style.opacity = '1';
    }, 10);
    
    setTimeout(() => {
        notification.style.opacity = '0';
        setTimeout(() => {
            document.body.removeChild(notification);
        }, 300);
    }, 3000);
}
