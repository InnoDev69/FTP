document.addEventListener('DOMContentLoaded', () => {
    checkForUpdates();
});

function saveWithTimer(key, value, minutes) {
    const now = new Date().getTime();
    const extraTime = minutes * 60 * 1000;
    
    const payload = {
        currentValue: value,
        changeAfter: now + extraTime
    };
    
    localStorage.setItem(key, JSON.stringify(payload));
}

function readAndUpdate(key, newValue) {
    const rawData = localStorage.getItem(key);
    if (!rawData) return null;

    const payload = JSON.parse(rawData);
    const now = new Date().getTime();

    if (payload.changeAfter && now >= payload.changeAfter) {
        const updatedPayload = {
            currentValue: newValue,
            changeAfter: null
        };
        localStorage.setItem(key, JSON.stringify(updatedPayload));
        
        return newValue;
    }

    return payload.currentValue;
}

function clearTimer(key) {
    localStorage.removeItem(key);
}

function getLaterOption() {
    const state = readAndUpdate('updateLater', 'false');
    return state === 'true';
}

function checkForUpdates() {
    if (!getLaterOption()) {
        fetch('/update/check')
            .then(response => response.json())
            .then(data => {
                if (data.update_available) {
                    const newVersion = data.version || "v0.0.0"; 

                    const badge = document.getElementById('nav-update-badge');
                    if (badge) {
                        badge.style.display = 'inline-block';
                        badge.textContent = '!';
                    }
                    console.log(data);

                    const updateModal = new ModalComponent('update-modal');

                    updateModal.title('System Update')
                        .content(`
                            <div style="text-align: center; padding: 10px;">
                                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color: #3B82F6; margin-bottom: 10px;">
                                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                                    <polyline points="7 10 12 15 17 10"></polyline>
                                    <line x1="12" y1="15" x2="12" y2="3"></line>
                                </svg>
                                
                                <div style="font-size: 0.9em; color: #ffffff; text-align: left; background: #0b121d; padding: 12px; border-radius: 6px;">
                                    <strong>Detected changes:</strong>
                                    <ul style="margin: 5px 0 0 0; padding-left: 0; list-style: none;">
                                        ${data.message.map(change => `<li>${change}</li>`).join('')}
                                    </ul>
                                </div>
                            </div>
                        `)
                        .buttons([
                            { label: 'Later', variant: 'secondary', action: 'close' },
                            { label: 'Update Now', variant: 'primary', action: 'install' }
                        ])
                        .render()
                        .show();

                    updateModal.onButton('close', () => {
                        saveWithTimer('updateLater', 'true', 1); // 1440 minutes = 24 hours
                        updateModal.hide();
                    });

                    updateModal.onButton('install', () => {
                        updateModal.hide();
                        installUpdate();
                    });
                } else {
                    const badge = document.getElementById('nav-update-badge');
                    if (badge) badge.style.display = 'none';
                }
            })
            .catch(error => console.error('Error checking for updates:', error));
    }
}

function installUpdate() {
    const progressModal = new ModalComponent('progress-modal');
    
    progressModal.title('Installing Update')
        .content(`
            <div style="text-align: center; padding: 30px 20px;">
                <div style="margin: 0 auto 15px auto; width: 40px; height: 40px; border: 4px solid #E5E7EB; border-top: 4px solid #3B82F6; border-radius: 50%; animation: spin 1s linear infinite;"></div>
                <style>@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }</style>
                
                <p style="font-size: 1.1em; color: #1F2937; margin-bottom: 5px;"><strong>Downloading update...</strong></p>
                <p style="color: #6B7280; font-size: 0.9em; margin: 0;">Do not close this window or power off the system.</p>
            </div>
        `)
        .buttons([]) 
        .render()
        .show();

    fetch('/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    })
    .then(response => {
        if (!response.ok) {
            return response.json().then(errData => {
                throw new Error(errData.message || 'Unknown server error');
            });
        }
        return response.json();
    })
    .then(data => {
        progressModal.content(`
            <div style="text-align: center; padding: 20px;">
                <div style="margin: 0 auto 15px auto; width: 40px; height: 40px; border: 4px solid #E5E7EB; border-top: 4px solid #F59E0B; border-radius: 50%; animation: spin 1s linear infinite;"></div>
                <p style="font-size: 1.1em; color: #1F2937;"><strong>Update applied!</strong></p>
                <p style="color: #6B7280; font-size: 0.9em;">Restarting server, please wait...</p>
            </div>
        `).render();

        clearTimer('updateLater');
        const badge = document.getElementById('nav-update-badge');
        if (badge) badge.style.display = 'none';

        waitForRestart();
    })
    .catch(error => {
        progressModal.content(`
            <div style="text-align: center; padding: 20px;">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#EF4444" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-bottom: 10px;">
                    <circle cx="12" cy="12" r="10"></circle>
                    <line x1="12" y1="8" x2="12" y2="12"></line>
                    <line x1="12" y1="16" x2="12.01" y2="16"></line>
                </svg>
                <p style="font-size: 1.1em; color: #1F2937;"><strong>Update failed</strong></p>
                <p style="color: #6B7280; font-size: 0.9em;">${error.message}</p>
            </div>
        `)
        .buttons([
            { label: 'Close', variant: 'secondary', action: 'close_error' }
        ])
        .render();

        progressModal.onButton('close_error', () => {
            progressModal.hide();
        });
    });
}

function waitForRestart() {
    setTimeout(() => {
        const interval = setInterval(() => {
            fetch('/', { method: 'HEAD' })
                .then(response => {
                    if (response.ok) {
                        clearInterval(interval);
                        window.location.reload(true);
                    }
                })
                .catch(() => {});
        }, 2500); 
    }, 2000);
}