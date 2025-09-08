const socket = io(); // Menghubungkan ke server Socket.IO
let startTime;
let frameCount = 0;
let lastFpsUpdateTime = 0;
let currentMode = 'BBOX';
let isDrawing = false;
let startPoint = null;
let videoElement = null;
let cursorEnabled = false;
let cursorTempDisplay = null;
let currentEditingObject = null;
let mirrorEnabled = false;
let currentColormap = 'INFERNO';


// Polygon drawing variables
let polygonPoints = [];
let isDrawingPolygon = false;
let polygonHelper = null;



// Initialize when page loads
document.addEventListener('DOMContentLoaded', function() {
    videoElement = document.getElementById('thermal-video');
    setupVideoInteraction();

    // Load data awal saat halaman dibuka
    loadSavedObjects();
    updateStatus();
    updateContactsList();
    updateGroupsList();
    loadMirrorStatus();
    loadColormapStatus();

    // Atur pembaruan otomatis (interval)
    setInterval(updateStatus, 2000);
    setInterval(updateObjectsList, 10000);

    // ========== Logika untuk Mengukur Latency ==========
    setInterval(() => {
        startTime = Date.now();
        socket.emit('ping_from_client');
    }, 2000); // Mengirim ping setiap 2 detik

    socket.on('pong_from_server', () => {
        const latency = Date.now() - startTime;
        const latencyElement = document.getElementById('network-latency');
        if (latencyElement) {
            latencyElement.textContent = `${latency} ms`;
            latencyElement.classList.remove('text-green-600', 'text-yellow-500', 'text-red-600');
            if (latency < 100) {
                latencyElement.classList.add('text-green-600');
            } else if (latency < 300) {
                latencyElement.classList.add('text-yellow-500');
            } else {
                latencyElement.classList.add('text-red-600');
            }
        }
    });

    // ========== Memulai Kalkulasi Display FPS ==========
    requestAnimationFrame(calculateDisplayFPS);

    // Create cursor temp display element
    cursorTempDisplay = document.createElement('div');
    cursorTempDisplay.className = 'cursor-info';
    cursorTempDisplay.style.position = 'fixed';
    cursorTempDisplay.style.display = 'none';
    document.body.appendChild(cursorTempDisplay);

    // Create polygon helper element INSIDE video-container
    const videoContainer = document.querySelector('.video-container');
    polygonHelper = document.createElement('div');
    polygonHelper.className = 'polygon-helper';
    polygonHelper.style.display = 'none';
    polygonHelper.style.position = 'absolute';
    polygonHelper.style.top = '0';
    polygonHelper.style.left = '0';
    polygonHelper.style.width = '100%';
    polygonHelper.style.height = '100%';
    polygonHelper.style.pointerEvents = 'none';
    polygonHelper.style.zIndex = '1000';
    videoContainer.appendChild(polygonHelper);

    setupModalHandlers();

    // Auto-update functions
    setInterval(updateObjectsList, 10000);
});

// ========== TAMBAHAN: Simple function untuk load objects yang tersimpan ==========
function loadSavedObjects() {
    console.log('🔄 Loading saved monitoring objects...');

    fetch('/api/load_objects', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success' && data.objects_count > 0) {
            console.log(`✅ Loaded ${data.objects_count} saved objects`);
            showNotification(`Loaded ${data.objects_count} saved monitoring objects`, 'success');
            updateObjectsList();
            updateStatus();
        } else {
            console.log('📄 No saved objects found');
        }
    })
    .catch(error => {
        console.error('❌ Error loading saved objects:', error);
        showNotification('Error loading saved objects', 'error');
    });
}

// ========== TAMBAHAN: Notification system ==========
function showNotification(message, type = 'info') {
    // Remove existing notifications
    const existingNotifications = document.querySelectorAll('.notification');
    existingNotifications.forEach(notif => notif.remove());

    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;

    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: ${type === 'success' ? '#28a745' : type === 'error' ? '#dc3545' : type === 'warning' ? '#ffc107' : '#17a2b8'};
        color: ${type === 'warning' ? '#333' : 'white'};
        padding: 12px 20px;
        border-radius: 6px;
        font-weight: bold;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        z-index: 10000;
        max-width: 300px;
        font-size: 14px;
        transition: all 0.3s ease;
    `;

    document.body.appendChild(notification);

    // Auto-remove after 4 seconds
    setTimeout(() => {
        notification.style.opacity = '0';
        notification.style.transform = 'translateX(100%)';
        setTimeout(() => notification.remove(), 300);
    }, 4000);

    // Click to dismiss
    notification.addEventListener('click', () => {
        notification.style.opacity = '0';
        notification.style.transform = 'translateX(100%)';
        setTimeout(() => notification.remove(), 300);
    });
}

// Setup modal event handlers
function setupModalHandlers() {
    // Close modal when clicking outside
    window.onclick = function(event) {
        const modal = document.getElementById('threshold-modal');
        if (event.target === modal) {
            closeThresholdModal();
        }
    }

    // Close modal with ESC key
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            const modal = document.getElementById('threshold-modal');
            if (modal.style.display === 'block') {
                closeThresholdModal();
            }

            // Cancel polygon drawing with ESC
            if (isDrawingPolygon) {
                cancelPolygonDrawing();
            }
        }
    });
}

// Setup video interaction handlers
function setupVideoInteraction() {
    const video = document.getElementById('thermal-video');
    const helper = document.getElementById('drawing-helper');

    video.addEventListener('mousedown', function(e) {
        e.preventDefault();

        if (currentMode === 'CURSOR') {
            return;
        }

        // Handle right-click for polygon completion
        if (e.button === 2 && currentMode === 'POLYGON' && isDrawingPolygon && polygonPoints.length >= 3) {
            completePolygon();
            return;
        }

        // Only handle left-click for point selection
        if (e.button !== 0) {
            return;
        }

        const rect = video.getBoundingClientRect();
        const scaleX = 640 / rect.width;
        const scaleY = 480 / rect.height;
        const x = Math.round((e.clientX - rect.left) * scaleX);
        const y = Math.round((e.clientY - rect.top) * scaleY);

        if (currentMode === 'POINT') {
            showThresholdModal('point', x, y);

        } else if (currentMode === 'POLYGON') {
            handlePolygonClick(x, y, e.clientX - rect.left, e.clientY - rect.top);
        } else {
            // Regular BBOX and LINE modes
            isDrawing = true;
            startPoint = {x: x, y: y, screenX: e.clientX - rect.left, screenY: e.clientY - rect.top};

            helper.style.display = 'block';
            helper.style.left = startPoint.screenX + 'px';
            helper.style.top = startPoint.screenY + 'px';
            helper.style.width = '0px';
            helper.style.height = '0px';
            helper.style.transform = 'none';
        }
    });

    video.addEventListener('mousemove', function(e) {
        const rect = video.getBoundingClientRect();

        if (currentMode === 'CURSOR' && cursorEnabled) {
            const scaleX = 640 / rect.width;
            const scaleY = 480 / rect.height;
            const x = Math.round((e.clientX - rect.left) * scaleX);
            const y = Math.round((e.clientY - rect.top) * scaleY);

            updateCursorPosition(x, y);

            cursorTempDisplay.style.left = (e.clientX + 15) + 'px';
            cursorTempDisplay.style.top = (e.clientY - 25) + 'px';
            cursorTempDisplay.style.display = 'block';

            return;
        }

        if (currentMode === 'POLYGON' && isDrawingPolygon) {
            updatePolygonPreview(e.clientX - rect.left, e.clientY - rect.top);
            return;
        }

        if (isDrawing && startPoint) {
            const currentScreenX = e.clientX - rect.left;
            const currentScreenY = e.clientY - rect.top;

            const helper = document.getElementById('drawing-helper');

            if (currentMode === 'BBOX') {
                const left = Math.min(startPoint.screenX, currentScreenX);
                const top = Math.min(startPoint.screenY, currentScreenY);
                const width = Math.abs(currentScreenX - startPoint.screenX);
                const height = Math.abs(currentScreenY - startPoint.screenY);

                helper.style.left = left + 'px';
                helper.style.top = top + 'px';
                helper.style.width = width + 'px';
                helper.style.height = height + 'px';
                helper.style.borderRadius = '4px';
                helper.style.transform = 'none';
            } else if (currentMode === 'LINE') {
                const deltaX = currentScreenX - startPoint.screenX;
                const deltaY = currentScreenY - startPoint.screenY;
                const length = Math.sqrt(deltaX * deltaX + deltaY * deltaY);
                const angle = Math.atan2(deltaY, deltaX) * 180 / Math.PI;

                helper.style.left = startPoint.screenX + 'px';
                helper.style.top = startPoint.screenY + 'px';
                helper.style.width = length + 'px';
                helper.style.height = '2px';
                helper.style.transform = `rotate(${angle}deg)`;
                helper.style.transformOrigin = '0 50%';
                helper.style.borderRadius = '1px';
            }
        }
    });

    video.addEventListener('mouseup', function(e) {
        if (currentMode === 'CURSOR' || currentMode === 'MANUAL4' || currentMode === 'POLYGON') {
            return;
        }

        if (isDrawing && startPoint) {
            const rect = video.getBoundingClientRect();
            const scaleX = 640 / rect.width;
            const scaleY = 480 / rect.height;
            const endX = Math.round((e.clientX - rect.left) * scaleX);
            const endY = Math.round((e.clientY - rect.top) * scaleY);

            if (currentMode === 'BBOX') {
                const width = Math.abs(endX - startPoint.x);
                const height = Math.abs(endY - startPoint.y);
                if (width < 10 || height < 10) {
                    showNotification('Area too small! Minimum 10x10 pixels.', 'warning');
                    resetDrawing();
                    return;
                }
                showThresholdModal('bbox', startPoint.x, startPoint.y, endX, endY);
            } else if (currentMode === 'LINE') {
                const distance = Math.sqrt((endX - startPoint.x) ** 2 + (endY - startPoint.y) ** 2);
                if (distance < 10) {
                    showNotification('Line too short! Minimum 10 pixels.', 'warning');
                    resetDrawing();
                    return;
                }
                showThresholdModal('line', startPoint.x, startPoint.y, endX, endY);
            }

            resetDrawing();
        }
    });

    video.addEventListener('mouseleave', function() {
        if (currentMode === 'CURSOR') {
            cursorTempDisplay.style.display = 'none';
            return;
        }

        resetDrawing();
    });

    // Prevent context menu on right-click for polygon mode
    video.addEventListener('contextmenu', function(e) {
        if (currentMode === 'POLYGON' && isDrawingPolygon) {
            e.preventDefault();
        }
    });
}

// Polygon drawing functions
function handlePolygonClick(x, y, screenX, screenY) {
    if (!isDrawingPolygon) {
        startPolygonDrawing();
    }

    // Store both video coordinates (for backend) and screen coordinates (for visual display)
    polygonPoints.push({
        x: x, y: y,  // Video coordinates for backend
        screenX: screenX, screenY: screenY  // Screen coordinates for visual display
    });
    updatePolygonVisual();
    updatePolygonInstruction();
}

function startPolygonDrawing() {
    isDrawingPolygon = true;
    polygonPoints = [];
    polygonHelper.style.display = 'block';
    document.getElementById('polygon-instruction').style.display = 'block';
}

function updatePolygonVisual() {
    if (polygonPoints.length === 0) return;

    polygonHelper.innerHTML = '';

    // Draw points and lines
    for (let i = 0; i < polygonPoints.length; i++) {
        const point = polygonPoints[i];

        // Create point marker using screen coordinates for visual display
        const marker = document.createElement('div');
        marker.style.cssText = `
            position: absolute;
            left: ${point.screenX}px;
            top: ${point.screenY}px;
            width: 12px;
            height: 12px;
            background: #8b5cf6;
            border: 3px solid white;
            border-radius: 50%;
            transform: translate(-50%, -50%);
            z-index: 1001;
            box-shadow: 0 2px 4px rgba(0,0,0,0.3);
        `;
        polygonHelper.appendChild(marker);

        // Add point number
        const number = document.createElement('div');
        number.style.cssText = `
            position: absolute;
            left: ${point.screenX + 15}px;
            top: ${point.screenY - 15}px;
            background: #8b5cf6;
            color: white;
            border-radius: 50%;
            width: 24px;
            height: 24px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 14px;
            font-weight: bold;
            z-index: 1002;
            box-shadow: 0 2px 4px rgba(0,0,0,0.3);
        `;
        number.textContent = i + 1;
        polygonHelper.appendChild(number);

        // Draw lines between points
        if (i > 0) {
            const prevPoint = polygonPoints[i - 1];
            const line = document.createElement('div');
            const deltaX = point.screenX - prevPoint.screenX;
            const deltaY = point.screenY - prevPoint.screenY;
            const length = Math.sqrt(deltaX * deltaX + deltaY * deltaY);
            const angle = Math.atan2(deltaY, deltaX) * 180 / Math.PI;

            line.style.cssText = `
                position: absolute;
                left: ${prevPoint.screenX}px;
                top: ${prevPoint.screenY}px;
                width: ${length}px;
                height: 3px;
                background: #8b5cf6;
                transform: translateY(-50%) rotate(${angle}deg);
                transform-origin: 0 50%;
                z-index: 1000;
                box-shadow: 0 1px 2px rgba(0,0,0,0.3);
            `;
            polygonHelper.appendChild(line);
        }
    }
}

function updatePolygonPreview(currentScreenX, currentScreenY) {
    if (polygonPoints.length === 0) return;
    updatePolygonVisual();

    // Draw preview line from last point to current mouse position
    const lastPoint = polygonPoints[polygonPoints.length - 1];
    const previewLine = document.createElement('div');
    const deltaX = currentScreenX - lastPoint.screenX;
    const deltaY = currentScreenY - lastPoint.screenY;
    const length = Math.sqrt(deltaX * deltaX + deltaY * deltaY);
    const angle = Math.atan2(deltaY, deltaX) * 180 / Math.PI;

    previewLine.style.cssText = `
        position: absolute;
        left: ${lastPoint.screenX}px;
        top: ${lastPoint.screenY}px;
        width: ${length}px;
        height: 2px;
        background: #8b5cf6;
        opacity: 0.5;
        transform: translateY(-50%) rotate(${angle}deg);
        transform-origin: 0 50%;
        z-index: 998;
    `;
    polygonHelper.appendChild(previewLine);
}

function completePolygon() {
    if (polygonPoints.length < 3) {
        showNotification('Polygon harus memiliki minimal 3 titik!', 'warning');
        return;
    }

    // Use video coordinates (x, y) for backend, not screen coordinates
    const coords = polygonPoints.map(point => [point.x, point.y]);
    showThresholdModal('polygon', coords);
    cancelPolygonDrawing();
}

function cancelPolygonDrawing() {
    isDrawingPolygon = false;
    polygonPoints = [];
    polygonHelper.style.display = 'none';
    polygonHelper.innerHTML = '';
    document.getElementById('polygon-instruction').style.display = 'none';
    document.getElementById('polygon-finish-container').style.display = 'none';
}

function updatePolygonInstruction() {
    const instruction = document.getElementById('polygon-instruction');
    if (!instruction) return;

    // Clear any existing content first
    instruction.innerHTML = '';

    if (polygonPoints.length === 0) {
        instruction.textContent = 'Klik untuk menambahkan titik ke-1. Klik kanan untuk menggambar poligon.';
    } else if (polygonPoints.length === 1) {
        instruction.textContent = 'Titik ke-1 ditambahkan. Klik untuk menambahkan titik ke-2.';
    } else if (polygonPoints.length === 2) {
        instruction.textContent = 'Titik ke-2 ditambahkan. Klik untuk menambahkan titik ke-3 atau klik kanan untuk menggambar poligon.';
    } else {
        instruction.textContent = `Titik ke-${polygonPoints.length} ditambahkan. Klik untuk menambahkan titik berikutnya atau klik kanan untuk menggambar poligon.`;
    }
}

// Reset drawing state
function resetDrawing() {
    isDrawing = false;
    startPoint = null;
    const helper = document.getElementById('drawing-helper');
    helper.style.display = 'none';
    helper.style.transform = 'none';
}

// Threshold Modal Functions
function showThresholdModal(type, x1, y1, x2, y2) {
    if (type === 'polygon') {
        currentEditingObject = {type, coords: x1};
    } else {
        currentEditingObject = {type, x1, y1, x2, y2};
    }

    const typeNames = {
        'point': 'Point Detection',
        'bbox': 'Bounding Box',
        'line': 'Line Detection',
        'polygon': 'Polygon Area'
    };

    document.getElementById('modal-title').textContent = `Set Threshold for ${typeNames[type]}`;
    document.getElementById('modal-threshold-input').value = 50; // Default 50°C untuk thermal real
    document.getElementById('threshold-modal').style.display = 'block';

    setTimeout(() => {
        document.getElementById('modal-threshold-input').focus();
        document.getElementById('modal-threshold-input').select();
    }, 100);
}

function closeThresholdModal() {
    document.getElementById('threshold-modal').style.display = 'none';
    currentEditingObject = null;
}

function saveThreshold() {
    const threshold = parseInt(document.getElementById('modal-threshold-input').value);

    if (threshold < 1 || threshold > 300) {
        showNotification('Threshold must be between 1-300°C', 'warning');
        return;
    }

    const name = prompt('Enter name for this object:', generateObjectName(currentEditingObject.type));

    if (!name || name.trim() === '') {
        showNotification('Object name cannot be empty', 'warning');
        return;
    }

    const objData = createObjectData(name.trim(), currentEditingObject, threshold);

    if (objData) {
        sendObjectData(objData);
        closeThresholdModal();
    }
}

// Generate default object name
function generateObjectName(type) {
    const timestamp = Date.now();
    const typeNames = {
        'point': 'Point',
        'bbox': 'Area',
        'line': 'Line',
        'polygon': 'Polygon'
    };
    return `${typeNames[type]}_${timestamp}`;
}

// Create object data based on type
function createObjectData(name, editingObject, threshold) {
    const {type} = editingObject;

    switch(type) {
        case 'point':
            const {x1, y1} = editingObject;
            return {
                name: name,
                type: 'POINT',
                coords: [x1, y1],
                threshold: threshold
            };

        case 'bbox':
            const {x1: bx1, y1: by1, x2, y2} = editingObject;
            const x = Math.min(bx1, x2);
            const y = Math.min(by1, y2);
            const w = Math.abs(x2 - bx1);
            const h = Math.abs(y2 - by1);

            return {
                name: name,
                type: 'BBOX',
                coords: [x, y, w, h],
                threshold: threshold
            };

        case 'line':
            const {x1: lx1, y1: ly1, x2: lx2, y2: ly2} = editingObject;
            return {
                name: name,
                type: 'LINE',
                coords: [[lx1, ly1], [lx2, ly2]],
                threshold: threshold
            };

        case 'polygon':
            return {
                name: name,
                type: 'POLYGON',
                coords: editingObject.coords,
                threshold: threshold
            };

        default:
            showNotification('Invalid object type', 'error');
            return null;
    }
}

// Send object data to server
function sendObjectData(objData) {
    fetch('/api/add_object', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(objData)
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            updateObjectsList();
            updateStatus();
            showNotification(`Object "${objData.name}" added successfully with threshold ${objData.threshold}°C`, 'success');
        } else {
            showNotification(`Failed to add object: ${data.message}`, 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification('Error adding object', 'error');
    });
}

// Cursor functions
function updateCursorPosition(x, y) {
    fetch('/api/set_cursor_pos', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({x: x, y: y})
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            const temp = data.cursor_temp || 0;
            cursorTempDisplay.textContent = `${temp.toFixed(1)}°C`;
            document.getElementById('cursor-temp-value').textContent = temp.toFixed(1);
        }
    })
    .catch(error => {
        console.error('Error updating cursor position:', error);
    });
}

function toggleCursor() {
    fetch('/api/toggle_cursor', {method: 'POST'})
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            cursorEnabled = data.cursor_enabled;
            const button = document.getElementById('cursor-toggle');
            const video = document.getElementById('thermal-video');

            if (cursorEnabled) {
                button.textContent = 'Disable Cursor';
                button.className = 'btn btn-warning';
                video.classList.add('cursor-crosshair');
            } else {
                button.textContent = 'Enable Cursor';
                button.className = 'btn btn-info';
                video.classList.remove('cursor-crosshair');
                cursorTempDisplay.style.display = 'none';
                document.getElementById('cursor-temp-value').textContent = '0.0';
            }

            showNotification(data.message, 'success');
        }
    })
    .catch(error => {
        console.error('Error toggling cursor:', error);
    });
}

// ========== TAMBAHAN: Mirror/flip video functions ==========
function loadMirrorStatus() {
    fetch('/api/get_mirror_status')
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            mirrorEnabled = data.mirror_enabled;
            updateMirrorButton();
        }
    })
    .catch(error => {
        console.error('Error loading mirror status:', error);
    });
}

function toggleMirror() {
    fetch('/api/toggle_mirror', {method: 'POST'})
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            mirrorEnabled = data.mirror_enabled;
            updateMirrorButton();
            showNotification(data.message, 'success');
        }
    })
    .catch(error => {
        console.error('Error toggling mirror:', error);
        showNotification('Error toggling mirror mode', 'error');
    });
}

function updateMirrorButton() {
    const button = document.getElementById('mirror-toggle');
    const indicator = document.getElementById('mirror-indicator');

    if (mirrorEnabled) {
        button.textContent = 'Disable Mirror';
        button.className = 'bg-yellow-400 text-gray-900 px-4 py-2 rounded font-semibold text-sm transition';
        if (indicator) indicator.style.display = 'block';
    } else {
        button.textContent = 'Mirror Video';
        button.className = 'bg-cyan-500 hover:bg-cyan-700 text-white px-4 py-2 rounded font-semibold text-sm transition';
        if (indicator) indicator.style.display = 'none';
    }
}

// ========== TAMBAHAN: Colormap functions ==========
function loadColormapStatus() {
    fetch('/api/get_colormap')
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            currentColormap = data.current_colormap;
            updateColormapSelect(data.available_colormaps, data.current_colormap);
        }
    })
    .catch(error => {
        console.error('Error loading colormap status:', error);
    });
}

function updateColormapSelect(availableColormaps, currentMap) {
    const select = document.getElementById('colormap-select');
    if (!select) return;

    select.innerHTML = '';

    availableColormaps.forEach(colormap => {
        const option = document.createElement('option');
        option.value = colormap;
        // Format colormap name untuk display (capitalize first letter, lowercase rest)
        option.textContent = colormap.charAt(0) + colormap.slice(1).toLowerCase();
        if (colormap === currentMap) {
            option.selected = true;
        }
        select.appendChild(option);
    });
}

function changeColormap() {
    const select = document.getElementById('colormap-select');
    const selectedColormap = select.value;

    if (selectedColormap === currentColormap) {
        return;
    }

    // Show loading state
    select.disabled = true;
    const originalValue = select.value;

    fetch('/api/set_colormap', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({colormap: selectedColormap})
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            currentColormap = data.colormap;
            showNotification(`Colormap changed to ${data.colormap.charAt(0) + data.colormap.slice(1).toLowerCase()}`, 'success');
        } else {
            showNotification(data.message, data.status === 'warning' ? 'warning' : 'error');
            // Reset select ke nilai sebelumnya jika gagal
            select.value = originalValue;
        }
    })
    .catch(error => {
        console.error('Error changing colormap:', error);
        showNotification('Error changing colormap', 'error');

        // Reset select ke nilai sebelumnya
        select.value = originalValue;
        loadColormapStatus();
    })
    .finally(() => {
        // Reset loading state
        select.disabled = false;
    });
}

function updateESP32Config() {
    const host = prompt('Enter ESP32 IP address:', document.getElementById('esp32-host').textContent);
    const port = prompt('Enter ESP32 port:', document.getElementById('esp32-port').textContent);

    if (host && port) {
        // Validasi basic
        if (!host.trim()) {
            showNotification('ESP32 host cannot be empty', 'warning');
            return;
        }

        const portNum = parseInt(port);
        if (isNaN(portNum) || portNum < 1 || portNum > 65535) {
            showNotification('Port must be a valid number between 1-65535', 'warning');
            return;
        }

        fetch('/api/set_esp32_config', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({host: host.trim(), port: portNum})
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                showNotification(`ESP32 config saved: ${data.host}:${data.port}`, 'success');
                // Update display immediately
                document.getElementById('esp32-host').textContent = data.host;
                document.getElementById('esp32-port').textContent = data.port;
            } else {
                showNotification(data.message, data.status === 'warning' ? 'warning' : 'error');
            }
            updateStatus();
        })
        .catch(error => {
            console.error('Error updating ESP32 config:', error);
            showNotification('Error updating ESP32 configuration', 'error');
        });
    }
}

// Mode and control functions
function updateMode() {
    const select = document.getElementById('monitoring-mode');
    currentMode = select.value;

    // Cancel any ongoing polygon drawing when switching modes
    if (isDrawingPolygon) {
        cancelPolygonDrawing();
    }

    const modeNames = {
        'POINT': 'Point',
        'BBOX': 'Bounding Box',
        'LINE': 'Line',
        'POLYGON': 'Polygon',
        'CURSOR': 'Free Cursor'
    };

    document.getElementById('current-mode').textContent = modeNames[currentMode];

    const cursorControls = document.getElementById('cursor-controls');
    const polygonInstruction = document.getElementById('polygon-instruction');
    const polygonFinishContainer = document.getElementById('polygon-finish-container');

    if (currentMode === 'CURSOR') {
        cursorControls.style.display = 'block';
        if (polygonInstruction) polygonInstruction.style.display = 'none';
        if (polygonFinishContainer) polygonFinishContainer.style.display = 'none';
    } else if (currentMode === 'POLYGON') {
        cursorControls.style.display = 'none';
        if (polygonInstruction) polygonInstruction.style.display = 'block';
        if (polygonFinishContainer) polygonFinishContainer.style.display = 'none';
    } else {
        cursorControls.style.display = 'none';
        if (polygonInstruction) polygonInstruction.style.display = 'none';
        if (polygonFinishContainer) polygonFinishContainer.style.display = 'none';
        if (cursorEnabled) toggleCursor();
    }
}

// Camera controls
function startCamera() {
    fetch('/api/start_camera', {method: 'POST'})
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            updateStatus();
            showNotification('ESP32 thermal camera started successfully', 'success');
        } else {
            showNotification(`Failed to start camera: ${data.message}`, 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification('Error starting ESP32 camera', 'error');
    });
}

function stopCamera() {
    fetch('/api/stop_camera', {method: 'POST'})
    .then(response => response.json())
    .then(data => {
        updateStatus();
        showNotification('ESP32 thermal camera stopped', 'info');
    })
    .catch(error => {
        console.error('Error:', error);
    });
}

function clearObjects() {
    if (!confirm('Are you sure you want to delete all monitoring objects?\n\nAll objects and threshold settings will be lost.\nA backup will be created automatically.')) {
        return;
    }

    fetch('/api/clear_objects', {method: 'POST'})
    .then(response => response.json())
    .then(data => {
        updateObjectsList();
        updateStatus();
        showNotification('All monitoring objects deleted successfully', 'success');
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification('Error clearing objects', 'error');
    });
}

// WhatsApp Personal Contacts functions
function addContact() {
    const nomor = document.getElementById('wa-nomor').value.trim();
    const nama = document.getElementById('wa-nama').value.trim() || 'No Name';

    if (!nomor) {
        showNotification('Please enter WhatsApp number!', 'warning');
        return;
    }

    if (!nomor.startsWith('62')) {
        showNotification('Number must start with 62 (example: 628123456789)', 'warning');
        return;
    }

    fetch('/api/manage_contacts', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({action: 'add', nomor: nomor, nama: nama})
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            document.getElementById('wa-nomor').value = '';
            document.getElementById('wa-nama').value = '';
            updateContactsList();
            showNotification(data.message, 'success');
        } else {
            showNotification('Error: ' + data.message, 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification('Error adding contact', 'error');
    });
}

function deleteContact(nomor) {
    if (!confirm(`Delete contact ${nomor}?`)) {
        return;
    }

    fetch('/api/manage_contacts', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({action: 'delete', nomor: nomor})
    })
    .then(response => response.json())
    .then(data => {
        updateContactsList();
        showNotification(data.message, data.status === 'success' ? 'success' : 'error');
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification('Error deleting contact', 'error');
    });
}

// WhatsApp Groups functions
function addGroup() {
    const groupId = document.getElementById('wa-group-id').value.trim();
    const nama = document.getElementById('wa-group-nama').value.trim() || 'No Name';

    if (!groupId) {
        showNotification('Please enter Group ID!', 'warning');
        return;
    }

    fetch('/api/manage_groups', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({action: 'add', group_id: groupId, nama: nama})
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            document.getElementById('wa-group-id').value = '';
            document.getElementById('wa-group-nama').value = '';
            updateGroupsList();
            showNotification(data.message, 'success');
        } else {
            showNotification('Error: ' + data.message, 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification('Error adding group', 'error');
    });
}

function deleteGroup(groupId) {
    if (!confirm(`Delete group ${groupId}?`)) {
        return;
    }

    fetch('/api/manage_groups', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({action: 'delete', group_id: groupId})
    })
    .then(response => response.json())
    .then(data => {
        updateGroupsList();
        showNotification(data.message, data.status === 'success' ? 'success' : 'error');
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification('Error deleting group', 'error');
    });
}

// Nama fungsi diubah agar lebih umum
function getGroupsFromBot() {
    // Show loading state
    // Perbaikan: Lebih baik menggunakan ID untuk memilih tombol
    const button = document.querySelector('button[onclick="getGroupsFromBot()"]'); // Pastikan onclick di HTML juga diubah
    const originalText = button.textContent;
    button.textContent = 'Loading...';
    button.disabled = true;

    // URL API diubah ke endpoint baru
    fetch('/api/get_whatsapp_bot_groups')
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success' && data.groups.length > 0) {
            // Bagian ini tetap sama
            showGroupSelectionModal(data.groups);
        } else {
            // Pesan notifikasi diubah
            showNotification('No groups found or WhatsApp Bot not connected', 'warning');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        // Pesan notifikasi diubah
        showNotification('Error getting groups. Make sure the Node.js WhatsApp Bot is running.', 'error');
    })
    .finally(() => {
        // Reset button state
        button.textContent = originalText;
        button.disabled = false;
    });
}

function showGroupSelectionModal(groups) {
    const modal = document.createElement('div');
    modal.className = 'threshold-modal';
    modal.style.display = 'block';

    modal.innerHTML = `
        <div class="modal-content" style="width: 600px; max-width: 90%;">
            <div class="modal-header">
                <h3>Select Groups to Add</h3>
                <span class="close" onclick="this.parentElement.parentElement.parentElement.remove()">&times;</span>
            </div>
            <div style="max-height: 400px; overflow-y: auto;">
                ${groups.map(group => `
                    <div style="display: flex; align-items: center; padding: 10px; border-bottom: 1px solid #eee;">
                        <input type="checkbox" id="group_${group.id}" value="${group.id}" style="margin-right: 10px;">
                        <label for="group_${group.id}" style="flex: 1; cursor: pointer;">
                            <strong>${group.name}</strong><br>
                            <small style="color: #666;">${group.id}</small><br>
                            <small style="color: #999;">${group.participantCount} participants</small>
                        </label>
                    </div>
                `).join('')}
            </div>
            <div style="margin-top: 15px; text-align: right;">
                <button class="btn btn-primary" onclick="addSelectedGroups(this)">Add Selected Groups</button>
                <button class="btn btn-secondary" onclick="this.parentElement.parentElement.parentElement.remove()">Cancel</button>
            </div>
        </div>
    `;

    document.body.appendChild(modal);
}

function addSelectedGroups(button) {
    const modal = button.closest('.threshold-modal');
    const checkboxes = modal.querySelectorAll('input[type="checkbox"]:checked');

    if (checkboxes.length === 0) {
        showNotification('Please select at least one group', 'warning');
        return;
    }

    let addedCount = 0;
    let errorCount = 0;

    // Show progress
    button.textContent = 'Adding...';
    button.disabled = true;

    // Add groups one by one
    const addPromises = Array.from(checkboxes).map(checkbox => {
        const groupId = checkbox.value;
        const groupName = checkbox.parentElement.querySelector('strong').textContent;

        return fetch('/api/manage_groups', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({action: 'add', group_id: groupId, nama: groupName})
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                addedCount++;
            } else {
                errorCount++;
                console.log(`Failed to add ${groupName}: ${data.message}`);
            }
        })
        .catch(() => {
            errorCount++;
        });
    });

    Promise.all(addPromises).then(() => {
        updateGroupsList();
        modal.remove();

        if (addedCount > 0) {
            showNotification(`Successfully added ${addedCount} group(s)${errorCount > 0 ? ` (${errorCount} failed)` : ''}`, 'success');
        } else {
            showNotification('Failed to add groups. They might already exist.', 'warning');
        }
    });
}

function testWhatsApp() {
    const nomor = document.getElementById('wa-test-nomor').value.trim();
    const groupId = document.getElementById('wa-test-group').value.trim();

    if (!nomor && !groupId) {
        showNotification('Please enter number or group ID for test!', 'warning');
        return;
    }

    // Show loading state
    const button = document.querySelector('button[onclick="testWhatsApp()"]');
    const originalText = button.textContent;
    button.textContent = 'Sending...';
    button.disabled = true;

    let testData = {};

    if (groupId) {
        testData = {group_id: groupId, type: 'group'};
    } else {
        testData = {nomor: nomor, type: 'personal'};
    }

    fetch('/api/test_whatsapp', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(testData)
    })
    .then(response => response.json())
    .then(data => {
        showNotification(data.message, data.status === 'success' ? 'success' : 'error');
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification('Error testing WhatsApp. Make sure WhatsApp Bot is running.', 'error');
    })
    .finally(() => {
        // Reset button state
        button.textContent = originalText;
        button.disabled = false;
    });
}

// Update object threshold
function updateObjectThreshold(objectName, inputElement) {
    const threshold = parseInt(inputElement.value);

    if (threshold < 1 || threshold > 300) {
        showNotification('Threshold must be between 1-300°C', 'warning');
        updateObjectsList(); // Reset nilai input
        return;
    }

    if (!confirm(`Update threshold for "${objectName}" to ${threshold}°C?`)) {
        updateObjectsList(); // Reset nilai input jika dibatalkan
        return;
    }

    fetch('/api/update_object_threshold', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({name: objectName, threshold: threshold})
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            updateObjectsList();
            updateStatus();
            showNotification(`Threshold for "${objectName}" updated to ${threshold}°C`, 'success');
        } else {
            showNotification(`Error: ${data.message}`, 'error');
            updateObjectsList();
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification('Error updating threshold', 'error');
        updateObjectsList();
    });
}

// Delete object
function deleteObject(objectName) {
    if (!confirm(`Delete object "${objectName}"?\n\nDeleted objects cannot be recovered.`)) {
        return;
    }

    fetch('/api/delete_object', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({name: objectName})
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            updateObjectsList();
            updateStatus();
            showNotification(`Object "${objectName}" deleted successfully`, 'success');
        } else {
            showNotification(`Error: ${data.message}`, 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification('Error deleting object', 'error');
    });
}

// Update functions
function updateContactsList() {
    fetch('/api/manage_contacts')
    .then(response => response.json())
    .then(data => {
        const contactsList = document.getElementById('contacts-list');
        if (data.contacts.length === 0) {
            contactsList.innerHTML = '<div class="py-2 text-center text-gray-500">No contacts yet</div>';
        } else {
            contactsList.innerHTML = data.contacts.map(contact => `
                <div class="contact-item bg-white rounded-xl shadow border border-gray-200 p-4 mb-4 flex justify-between items-center">
                    <div>
                        <strong class="text-lg">${contact.Nama}</strong><br>
                        <small class="text-gray-700">${contact.Nomor_WhatsApp}</small>
                    </div>
                    <button class="bg-red-500 hover:bg-red-600 text-white px-4 py-1 rounded text-sm font-semibold" onclick="deleteContact('${contact.Nomor_WhatsApp}')">Delete</button>
                </div>
            `).join('');
        }
    })
    .catch(error => {
        console.error('Error updating contacts list:', error);
    });
}

function updateGroupsList() {
    fetch('/api/manage_groups')
    .then(response => response.json())
    .then(data => {
        const groupsList = document.getElementById('groups-list');
        if (data.groups.length === 0) {
            groupsList.innerHTML = '<div class="py-2 text-center text-gray-500">No groups yet</div>';
        } else {
            groupsList.innerHTML = data.groups.map(group => `
                <div class="contact-item bg-white rounded-xl shadow border border-gray-200 p-4 mb-4 flex justify-between items-center">
                    <div>
                        <strong class="text-lg">${group.Nama}</strong><br>
                        <small class="text-gray-700" style="font-family: monospace;">${group.Group_ID}</small>
                    </div>
                    <button class="bg-red-500 hover:bg-red-600 text-white px-4 py-1 rounded text-sm font-semibold" onclick="deleteGroup('${group.Group_ID}')">Delete</button>
                </div>
            `).join('');
        }
    })
    .catch(error => {
        console.error('Error updating groups list:', error);
    });
}

// Status update with ESP32 support
function updateStatus() {
    fetch('/api/get_status')
    .then(response => response.json())
    .then(data => {
        document.getElementById('camera-status').textContent = data.camera_active ? 'Running' : 'Stopped';
        document.getElementById('max-temp').textContent = (data.max_temp || 0).toFixed(1);
        document.getElementById('objects-count').textContent = data.objects_count;

        document.getElementById('status-camera').textContent = data.camera_active ? 'Running' : 'Stopped';
        document.getElementById('status-max-temp').textContent = (data.max_temp || 0).toFixed(1) + '°C';
        document.getElementById('status-objects').textContent = data.objects_count;

        // Update ESP32 status
        const esp32Status = document.getElementById('status-esp32');
        if (esp32Status) {
            esp32Status.textContent = data.esp32_status || 'Unknown';
            esp32Status.className = data.esp32_status === 'Connected' ? 'normal' : 'overheat';
        }

        // Update ESP32 config display dengan nilai actual
        const esp32Host = document.getElementById('esp32-host');
        const esp32Port = document.getElementById('esp32-port');
        if (esp32Host && data.esp32_host) {
            esp32Host.textContent = data.esp32_host;
        }
        if (esp32Port && data.esp32_port) {
            esp32Port.textContent = data.esp32_port;
        }

        // Update WhatsApp Bot status
        const whatsappStatus = document.getElementById('whatsapp_bot_status');
        if (whatsappStatus) {
            whatsappStatus.textContent = data.whatsapp_bot_status || 'Unknown';

            // Tetap menggunakan class 'normal' dan 'overheat' seperti kode lama
            // 'font-bold' ditambahkan agar tidak hilang saat class diubah
            whatsappStatus.className = 'font-bold ' + (data.whatsapp_bot_status === 'Connected' ? 'normal' : 'overheat');
        }

        // Update InfluxDB status (if exists)
        const influxStatus = document.getElementById('status-influxdb');
        if (influxStatus) {
            influxStatus.textContent = data.influxdb_status || 'Unknown';
            influxStatus.className = data.influxdb_status === 'Connected' ? 'normal' : 'overheat';
        }

        // ========== TAMBAHAN: Update simple persistence status ==========
        const persistenceStatus = document.getElementById('status-persistence');
        if (persistenceStatus) {
            persistenceStatus.textContent = 'Active';
            persistenceStatus.className = 'normal';
        }

        // ========== TAMBAHAN: Update colormap status ==========
        const colormapStatus = document.getElementById('status-colormap');
        if (colormapStatus && data.current_colormap) {
            colormapStatus.textContent = data.current_colormap.charAt(0) + data.current_colormap.slice(1).toLowerCase();
            colormapStatus.className = 'normal';
        }

        if (data.cursor_enabled && currentMode === 'CURSOR') {
            document.getElementById('cursor-temp-value').textContent = (data.cursor_temp || 0).toFixed(1);
        }

        // Update mirror status
        if (data.mirror_enabled !== undefined && data.mirror_enabled !== mirrorEnabled) {
            mirrorEnabled = data.mirror_enabled;
            updateMirrorButton();
        }

        // Update colormap jika berbeda (real-time sync)
        if (data.current_colormap && data.current_colormap !== currentColormap) {
            currentColormap = data.current_colormap;
            updateColormapSelect(data.available_colormaps, data.current_colormap);
        }

        const statusElements = ['camera-status', 'status-camera'];
        statusElements.forEach(id => {
            const element = document.getElementById(id);
            element.className = data.camera_active ? 'normal' : 'status-value';
        });

        const tempElements = ['max-temp', 'status-max-temp'];
        tempElements.forEach(id => {
            const element = document.getElementById(id);
            element.className = 'status-value';
        });

        const overheatAlert = document.getElementById('overheat-alert');
        const overheatList = document.getElementById('overheat-list');

        // Gunakan 'persistent_overheat_list' untuk menjaga alert tetap tampil
        if (data.persistent_overheat_list && data.persistent_overheat_list.length > 0) {
            overheatAlert.style.display = 'block';
            // Buat daftar dari data persisten
            overheatList.innerHTML = data.persistent_overheat_list.map(obj =>
                `<div>• ${obj.name} (${obj.type}): ${(obj.temp || 0).toFixed(1)}°C (Limit: ${obj.threshold}°C)</div>`
            ).join('');
        } else {
            // Hanya sembunyikan jika tidak ada lagi overheat yang tercatat
            overheatAlert.style.display = 'none';
        }
        // ========== TAMBAHAN: Update Processing FPS ==========
        const processingFpsEl = document.getElementById('processing-fps');
        if (processingFpsEl) {
            processingFpsEl.textContent = data.processing_fps || 0;
        }
    })
    .catch(error => {
        console.error('Error updating status:', error);
    });
}

// Objects list with real temperature formatting
function updateObjectsList() {
   fetch('/api/get_objects')
   .then(response => response.json())
   .then(data => {
       const objectsList = document.getElementById('objects-list');

       if (data.objects.length === 0) {
           objectsList.innerHTML = '<div class="py-5 text-center text-gray-500">No objects added yet</div>';
       } else {
           objectsList.innerHTML = data.objects.map((obj, index) => {
               const temp = obj.temp || 0;
               const overheat = temp >= obj.threshold;

               // Add show points button for polygon objects
               const showPointsButton = obj.type === 'POLYGON' ?
                   `<button class="bg-purple-600 hover:bg-purple-700 text-white px-3 py-1 rounded text-xs font-semibold" onclick="showPolygonPoints('${obj.name}', ${JSON.stringify(obj.coords).replace(/"/g, '&quot;')})"
                           title="Show polygon points">Show Points</button>` : '';

               return `
                   <div class="object-item bg-white rounded-xl shadow border border-gray-200 p-4 mb-4">
                       <div class="object-header flex justify-between items-center mb-2">
                           <div class="object-info">
                               <strong class="text-lg">${obj.name}</strong><br>
                               <small class="uppercase text-gray-500">${obj.type}</small>
                           </div>
                           <div class="object-temp ${overheat ? 'bg-red-600' : 'bg-green-600'} text-white text-base font-bold px-3 py-1 rounded">
                               ${temp.toFixed(1)}°C
                           </div>
                       </div>
                       <div class="object-controls flex flex-wrap gap-2 items-center mt-2">
                           <div class="threshold-control flex items-center gap-2 bg-gray-50 border border-gray-200 rounded p-2">
                               <label class="text-xs font-semibold">Threshold:</label>
                               <input type="number" class="threshold-input w-20 p-1 border border-gray-300 rounded text-sm" value="${obj.threshold}" min="1" max="300"
                                      id="threshold-${index}"
                                      title="Set individual threshold for this object">
                               <span class="text-xs">°C</span>
                               <button class="bg-blue-600 hover:bg-blue-700 text-white px-3 py-1 rounded text-xs font-semibold" onclick="updateObjectThreshold('${obj.name}', document.getElementById('threshold-${index}'))"
                                       title="Apply new threshold">OK</button>
                           </div>
                           ${showPointsButton}
                           <button class="bg-red-600 hover:bg-red-700 text-white px-4 py-1 rounded text-sm font-semibold" onclick="deleteObject('${obj.name}')"
                                   title="Delete this object">Delete</button>
                       </div>
                   </div>
               `;
           }).join('');
       }
   })
   .catch(error => {
       console.error('Error updating objects list:', error);
   });
}

// Function to show polygon points on the video
function showPolygonPoints(polygonName, coords) {
    // Create a temporary helper element to show the points
    const videoContainer = document.querySelector('.video-container');
    const tempHelper = document.createElement('div');
    tempHelper.className = 'temp-polygon-points';
    tempHelper.style.cssText = `
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        pointer-events: none;
        z-index: 1000;
    `;

    // Get video dimensions for scaling
    const video = document.getElementById('thermal-video');
    const rect = video.getBoundingClientRect();
    const scaleX = rect.width / 80;
    const scaleY = rect.height / 62;

    // Draw points and lines
    for (let i = 0; i < coords.length; i++) {
        const point = coords[i];
        const screenX = point[0] * scaleX;
        const screenY = point[1] * scaleY;

        // Create point marker
        const marker = document.createElement('div');
        marker.style.cssText = `
            position: absolute;
            left: ${screenX}px;
            top: ${screenY}px;
            width: 8px;
            height: 8px;
            background: #8b5cf6;
            border: 2px solid white;
            border-radius: 50%;
            transform: translate(-50%, -50%);
            z-index: 1001;
        `;
        tempHelper.appendChild(marker);

        // Add point number
        const number = document.createElement('div');
        number.style.cssText = `
            position: absolute;
            left: ${screenX + 10}px;
            top: ${screenY - 10}px;
            background: #8b5cf6;
            color: white;
            border-radius: 50%;
            width: 20px;
            height: 20px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 12px;
            font-weight: bold;
            z-index: 1002;
        `;
        number.textContent = i + 1;
        tempHelper.appendChild(number);

        // Draw lines between points
        if (i > 0) {
            const prevPoint = coords[i - 1];
            const prevScreenX = prevPoint[0] * scaleX;
            const prevScreenY = prevPoint[1] * scaleY;
            const deltaX = screenX - prevScreenX;
            const deltaY = screenY - prevScreenY;
            const length = Math.sqrt(deltaX * deltaX + deltaY * deltaY);
            const angle = Math.atan2(deltaY, deltaX) * 180 / Math.PI;

            const line = document.createElement('div');
            line.style.cssText = `
                position: absolute;
                left: ${prevScreenX}px;
                top: ${prevScreenY}px;
                width: ${length}px;
                height: 2px;
                background: #8b5cf6;
                transform: translateY(-50%) rotate(${angle}deg);
                transform-origin: 0 50%;
                z-index: 1000;
            `;
            tempHelper.appendChild(line);
        }
    }

    // Close the polygon
    if (coords.length > 2) {
        const firstPoint = coords[0];
        const lastPoint = coords[coords.length - 1];
        const firstScreenX = firstPoint[0] * scaleX;
        const firstScreenY = firstPoint[1] * scaleY;
        const lastScreenX = lastPoint[0] * scaleX;
        const lastScreenY = lastPoint[1] * scaleY;
        const deltaX = firstScreenX - lastScreenX;
        const deltaY = firstScreenY - lastScreenY;
        const length = Math.sqrt(deltaX * deltaX + deltaY * deltaY);
        const angle = Math.atan2(deltaY, deltaX) * 180 / Math.PI;

        const closingLine = document.createElement('div');
        closingLine.style.cssText = `
            position: absolute;
            left: ${lastScreenX}px;
            top: ${lastScreenY}px;
            width: ${length}px;
            height: 2px;
            background: #8b5cf6;
            transform: translateY(-50%) rotate(${angle}deg);
            transform-origin: 0 50%;
            z-index: 1000;
        `;
        tempHelper.appendChild(closingLine);
    }

    videoContainer.appendChild(tempHelper);

    // Auto-remove after 5 seconds
    setTimeout(() => {
        if (tempHelper.parentNode) {
            tempHelper.parentNode.removeChild(tempHelper);
        }
    }, 5000);

    showNotification(`Showing points for ${polygonName}`, 'info');
}

// function calculateDisplayFPS(timestamp) {
//     frameCount++;
//     if (timestamp - lastFpsUpdateTime > 1000) { // Update setiap 1 detik
//         const fps = frameCount;
//         document.getElementById('display-fps-overlay').textContent = fps;
//         document.getElementById('display-fps').textContent = fps;

//         // Reset
//         frameCount = 0;
//         lastFpsUpdateTime = timestamp;
//     }
//     // Terus panggil fungsi ini untuk frame berikutnya
//     requestAnimationFrame(calculateDisplayFPS);
// }
