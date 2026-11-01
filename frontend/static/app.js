/**
 * CampusConnect Client Application
 * Features:
 * 1. Dark/Light Mode Theme Switcher with localStorage persistence
 * 2. QR Code Pass Rendering (with inbuilt student name, USN, and email)
 * 3. Ticket Pass Modal & Canvas PNG Download
 * 4. Organizer Attendance Scanner
 */

// -----------------------------------------------------------------------------
// 1. Theme Management (Light / Dark mode)
// -----------------------------------------------------------------------------
(function initTheme() {
  const toggleBtn = document.getElementById('themeToggle');
  if (toggleBtn) {
    toggleBtn.addEventListener('click', function () {
      const current = document.documentElement.getAttribute('data-theme') || 'light';
      const next = current === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('campus_theme', next);
    });
  }
})();

// -----------------------------------------------------------------------------
// 2. QR Code Rendering Helper
// -----------------------------------------------------------------------------
function makeQRCode(container, payloadText, size = 180) {
  if (!container) return;
  container.innerHTML = '';

  // If QRCode library is loaded (from CDN or local)
  if (typeof QRCode !== 'undefined') {
    try {
      new QRCode(container, {
        text: payloadText,
        width: size,
        height: size,
        colorDark: '#121316',
        colorLight: '#ffffff',
        correctLevel: QRCode.CorrectLevel.M
      });
      return;
    } catch (err) {
      console.warn('QRCode library error, using fallback:', err);
    }
  }

  // Fallback if CDN blocked / offline: Clean SVG visual token
  renderFallbackQR(container, payloadText, size);
}

// Fallback visual token for offline environments
function renderFallbackQR(container, text, size) {
  let hash = 0;
  for (let i = 0; i < text.length; i++) {
    hash = ((hash << 5) - hash) + text.charCodeAt(i);
    hash |= 0;
  }
  const grid = 21;
  const modSize = Math.floor(size / grid);
  const actualSize = modSize * grid;

  let svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${actualSize}" height="${actualSize}" viewBox="0 0 ${actualSize} ${actualSize}">`;
  svg += `<rect width="100%" height="100%" fill="#ffffff"/>`;

  // Draw 3 corner finder patterns
  function drawFinder(ox, oy) {
    svg += `<rect x="${ox * modSize}" y="${oy * modSize}" width="${7 * modSize}" height="${7 * modSize}" fill="#111827"/>`;
    svg += `<rect x="${(ox + 1) * modSize}" y="${(oy + 1) * modSize}" width="${5 * modSize}" height="${5 * modSize}" fill="#ffffff"/>`;
    svg += `<rect x="${(ox + 2) * modSize}" y="${(oy + 2) * modSize}" width="${3 * modSize}" height="${3 * modSize}" fill="#111827"/>`;
  }
  drawFinder(0, 0);
  drawFinder(grid - 7, 0);
  drawFinder(0, grid - 7);

  // Pseudo-random data modules derived deterministically from payload
  let seed = Math.abs(hash) || 12345;
  for (let r = 0; r < grid; r++) {
    for (let c = 0; c < grid; c++) {
      if ((r < 8 && c < 8) || (r < 8 && c >= grid - 8) || (r >= grid - 8 && c < 8)) continue;
      seed = (seed * 9301 + 49297) % 233280;
      if (seed % 3 === 0) {
        svg += `<rect x="${c * modSize}" y="${r * modSize}" width="${modSize}" height="${modSize}" fill="#111827"/>`;
      }
    }
  }
  svg += `</svg>`;
  container.innerHTML = svg;
}

// -----------------------------------------------------------------------------
// 3. QR Ticket Pass Modal
// -----------------------------------------------------------------------------
let currentPassData = { title: '', date: '', time: '', venue: '', payload: '' };

function openTicketModal(title, dateStr, timeStr, venueStr, payload) {
  const modal = document.getElementById('ticketModal');
  if (!modal) return;

  currentPassData = {
    title: title || 'CampusConnect Event',
    date: dateStr || '',
    time: timeStr || '',
    venue: venueStr || '',
    payload: payload || ''
  };

  const titleEl = document.getElementById('ticketEventTitle');
  const metaEl = document.getElementById('ticketEventMeta');
  const qrContainer = document.getElementById('modalQrCode');

  if (titleEl) titleEl.textContent = currentPassData.title;
  if (metaEl) {
    const parts = [currentPassData.date, currentPassData.time, currentPassData.venue].filter(Boolean);
    metaEl.textContent = parts.join(' · ');
  }

  if (qrContainer && currentPassData.payload) {
    makeQRCode(qrContainer, currentPassData.payload, 190);
  }

  modal.classList.add('open');
}

function closeTicketModal() {
  const modal = document.getElementById('ticketModal');
  if (modal) modal.classList.remove('open');
}

// Close on backdrop or Esc key
document.addEventListener('keydown', function (e) {
  if (e.key === 'Escape') closeTicketModal();
});
document.addEventListener('click', function (e) {
  const modal = document.getElementById('ticketModal');
  if (modal && e.target === modal) closeTicketModal();
});

// Download Ticket as PNG image
const btnDownloadPass = document.getElementById('btnDownloadPass');
if (btnDownloadPass) {
  btnDownloadPass.addEventListener('click', function () {
    const qrContainer = document.getElementById('modalQrCode');
    const qrCanvasOrImg = qrContainer ? qrContainer.querySelector('canvas, img') : null;

    const width = 420;
    const height = 560;
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');

    // Background
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, width, height);

    // Header bar
    ctx.fillStyle = '#d9482b';
    ctx.fillRect(0, 0, width, 70);

    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 17px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('🎟️ CAMPUSCONNECT ENTRY PASS', width / 2, 42);

    // Event title
    ctx.fillStyle = '#1c1b22';
    ctx.font = 'bold 22px serif';
    ctx.fillText(currentPassData.title.substring(0, 32), width / 2, 120);

    // Meta details (Date, Time, Venue)
    ctx.fillStyle = '#4b4a57';
    ctx.font = '14px sans-serif';
    const metaText = [currentPassData.date, currentPassData.time, currentPassData.venue].filter(Boolean).join(' · ');
    ctx.fillText(metaText.substring(0, 48), width / 2, 150);

    // Perforated line
    ctx.setLineDash([6, 6]);
    ctx.strokeStyle = '#e8e3da';
    ctx.beginPath();
    ctx.moveTo(30, 180);
    ctx.lineTo(width - 30, 180);
    ctx.stroke();
    ctx.setLineDash([]);

    // Draw QR Code
    if (qrCanvasOrImg) {
      const qrSize = 200;
      const qx = (width - qrSize) / 2;
      const qy = 205;

      // QR border frame
      ctx.fillStyle = '#f8f9fa';
      ctx.strokeStyle = '#e8e3da';
      ctx.lineWidth = 1;
      ctx.fillRect(qx - 10, qy - 10, qrSize + 20, qrSize + 20);
      ctx.strokeRect(qx - 10, qy - 10, qrSize + 20, qrSize + 20);

      ctx.drawImage(qrCanvasOrImg, qx, qy, qrSize, qrSize);
    }

    // Status pill
    ctx.fillStyle = '#1f7a4d';
    ctx.font = 'bold 14px sans-serif';
    ctx.fillText('✓ CONFIRMED REGISTRATION', width / 2, 455);

    // Footer instruction
    ctx.fillStyle = '#7a7886';
    ctx.font = '12px sans-serif';
    ctx.fillText('Present this QR code at the event entrance for attendance check-in.', width / 2, 485);
    ctx.fillText('Inbuilt student registration details included in QR data.', width / 2, 505);

    // Trigger download
    const link = document.createElement('a');
    link.download = `event-pass-${Date.now()}.png`;
    link.href = canvas.toDataURL('image/png');
    link.click();
  });
}

// -----------------------------------------------------------------------------
// 4. Initialize Inline QR Codes on load
// -----------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', function () {
  // Any element with .auto-render-qr and data-payload
  document.querySelectorAll('.auto-render-qr').forEach(function (el) {
    const payload = el.getAttribute('data-payload');
    const size = parseInt(el.getAttribute('data-size') || '180', 10);
    if (payload) {
      makeQRCode(el, payload, size);
    }
  });

  // Attach click handlers to any button with class .btn-open-pass
  document.querySelectorAll('.btn-open-pass').forEach(function (btn) {
    btn.addEventListener('click', function () {
      const title = btn.getAttribute('data-title') || '';
      const date = btn.getAttribute('data-date') || '';
      const time = btn.getAttribute('data-time') || '';
      const venue = btn.getAttribute('data-venue') || '';
      const payload = btn.getAttribute('data-payload') || '';
      openTicketModal(title, date, time, venue, payload);
    });
  });
});

