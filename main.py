from flask import Flask, render_template_string, request, jsonify
import requests
import hashlib

app = Flask(__name__)

# Giao diện HTML giữ nguyên toàn bộ, đã trỏ endpoint login về backend Python
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, minimum-scale=1.0, user-scalable=no, viewport-fit=cover" />
<meta name="format-detection" content="telephone=no" />
<title>AUTO CƯỢC LC79 — HuyDaiXuVN</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/crypto-js/4.2.0/crypto-js.min.js"></script>
<style>
  /* ================= RESET & CHỐNG ZOOM ================= */
  * { margin: 0; padding: 0; box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  html, body {
    touch-action: manipulation;
    -webkit-text-size-adjust: 100%;
    -ms-text-size-adjust: 100%;
    overscroll-behavior: none;
    height: 100%;
  }
  :root {
    --primary: #e63946;
    --primary-2: #ff4d6d;
    --primary-dark: #b5172a;
    --accent: #ffb703;
    --gold: #f4b400;
    --ink: #0d1117;
    --muted: #6b7280;
    --line: #e5e7eb;
    --bg: #f6f7fb;
    --success: #10b981;
    --danger: #ef4444;
    --shadow-md: 0 8px 24px rgba(15, 23, 42, 0.06);
    --shadow-lg: 0 20px 60px rgba(15, 23, 42, 0.08);
  }
  body {
    font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
    background: var(--bg);
    color: #1f2937;
    display: flex;
    flex-direction: column;
    min-height: 100vh;
    line-height: 1.5;
    -webkit-font-smoothing: antialiased;
    user-select: none;
    -webkit-user-select: none;
  }
  input, textarea { user-select: text; -webkit-user-select: text; }

  /* ================= HEADER ================= */
  .header {
    background: rgba(255, 255, 255, 0.9);
    backdrop-filter: saturate(180%) blur(14px);
    -webkit-backdrop-filter: saturate(180%) blur(14px);
    border-bottom: 1px solid rgba(15, 23, 42, 0.06);
    position: sticky; top: 0; z-index: 100;
  }
  .header-inner {
    max-width: 1280px; margin: 0 auto;
    padding: 12px 20px;
    display: flex; align-items: center; justify-content: space-between;
    gap: 12px;
  }
  .brand { display: flex; align-items: center; gap: 10px; text-decoration: none; color: var(--ink); }
  .brand-mark {
    width: 40px; height: 40px; border-radius: 11px;
    background: radial-gradient(circle at 30% 30%, #ff9a9e 0%, transparent 55%),
                linear-gradient(135deg, var(--primary-2), var(--primary-dark));
    display: grid; place-items: center;
    color: #fff; font-family: 'Space Grotesk', sans-serif;
    font-weight: 700; font-size: 12px;
    box-shadow: 0 6px 16px rgba(230, 57, 70, 0.35);
  }
  .brand-name { display: flex; flex-direction: column; line-height: 1.15; }
  .brand-name strong {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 14px; font-weight: 700;
    color: var(--ink); letter-spacing: 0.3px;
  }
  .brand-name small {
    font-size: 10px; letter-spacing: 1.8px;
    color: var(--muted); text-transform: uppercase; font-weight: 600;
  }
  .header-right { display: flex; align-items: center; gap: 10px; }
  .user-chip {
    display: flex; align-items: center; gap: 8px;
    padding: 5px 12px 5px 5px;
    background: #fff; border: 1px solid var(--line);
    border-radius: 999px;
    font-size: 13px; font-weight: 600; color: var(--ink);
    max-width: 200px;
  }
  .user-chip .avatar {
    width: 28px; height: 28px; border-radius: 50%;
    background: linear-gradient(135deg, var(--primary-2), var(--primary-dark));
    color: #fff; display: grid; place-items: center;
    font-size: 11px; font-weight: 700; text-transform: uppercase;
    flex-shrink: 0;
  }
  .user-chip span {
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .btn-logout {
    padding: 8px 14px;
    background: #fef2f2; color: var(--primary);
    border: 1px solid #fecaca; border-radius: 9px;
    font-family: inherit; font-size: 13px; font-weight: 600;
    cursor: pointer; display: inline-flex; align-items: center; gap: 6px;
    transition: all 0.2s;
  }
  .btn-logout:hover { background: #fee2e2; border-color: #fca5a5; }

  /* ================= LOGIN VIEW ================= */
  .main {
    flex: 1;
    display: grid;
    grid-template-columns: 1fr 1fr;
    max-width: 1180px;
    width: 100%;
    margin: 0 auto;
    padding: 24px 20px;
    gap: 32px;
    align-items: center;
  }
  .brand-panel {
    position: relative;
    min-height: 520px;
    border-radius: 22px;
    padding: 40px 36px;
    color: #fff;
    background:
      radial-gradient(circle at 20% 10%, rgba(255, 183, 3, 0.18) 0%, transparent 40%),
      radial-gradient(circle at 90% 90%, rgba(255, 77, 109, 0.25) 0%, transparent 45%),
      linear-gradient(150deg, #1a1f2e 0%, #0d1117 60%, #1a0a10 100%);
    overflow: hidden;
    display: flex; flex-direction: column; justify-content: space-between;
    box-shadow: var(--shadow-lg);
    isolation: isolate;
  }
  .brand-panel::before {
    content: ''; position: absolute; inset: 0;
    background-image:
      linear-gradient(rgba(255,255,255,0.035) 1px, transparent 1px),
      linear-gradient(90deg, rgba(255,255,255,0.035) 1px, transparent 1px);
    background-size: 40px 40px;
    mask-image: radial-gradient(ellipse at 50% 0%, #000 30%, transparent 75%);
    -webkit-mask-image: radial-gradient(ellipse at 50% 0%, #000 30%, transparent 75%);
  }
  .brand-panel > * { position: relative; z-index: 1; }
  .badge-new {
    display: inline-flex; align-items: center; gap: 7px;
    padding: 5px 11px 5px 7px; border-radius: 999px;
    font-size: 11px; font-weight: 600;
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.12);
    width: fit-content;
  }
  .badge-new .dot {
    width: 6px; height: 6px; border-radius: 50%;
    background: var(--success);
    box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.25);
  }
  .brand-panel h1 {
    font-family: 'Space Grotesk', sans-serif;
    font-size: clamp(24px, 3vw, 36px);
    line-height: 1.18; font-weight: 700;
    letter-spacing: -0.7px;
    margin: 18px 0 12px; max-width: 440px;
  }
  .brand-panel h1 .grad {
    background: linear-gradient(120deg, #ff4d6d 0%, #ffb703 100%);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
  }
  .brand-panel p.lead {
    font-size: 14.5px; line-height: 1.7;
    color: rgba(255, 255, 255, 0.65); max-width: 400px;
  }
  .feature-list { display: grid; gap: 10px; margin-top: 24px; }
  .feature-item {
    display: flex; align-items: center; gap: 12px;
    padding: 10px 14px; border-radius: 11px;
    background: rgba(255, 255, 255, 0.04);
    border: 1px solid rgba(255, 255, 255, 0.06);
  }
  .feature-icon {
    width: 32px; height: 32px; border-radius: 9px;
    background: linear-gradient(135deg, rgba(255, 77, 109, 0.25), rgba(255, 183, 3, 0.2));
    display: grid; place-items: center; flex-shrink: 0; color: #ffb703;
  }
  .feature-item strong {
    display: block; font-size: 13px; font-weight: 600;
    color: #fff; margin-bottom: 1px;
  }
  .feature-item small { font-size: 11.5px; color: rgba(255, 255, 255, 0.5); }

  .login-panel { display: flex; justify-content: center; align-items: center; }
  .login-card {
    width: 100%; max-width: 420px;
    background: #fff; border-radius: 18px;
    padding: 36px 30px 32px;
    border: 1px solid var(--line);
    box-shadow: var(--shadow-md);
  }
  .login-card h2 {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 22px; font-weight: 700;
    letter-spacing: -0.4px; color: var(--ink);
    margin-bottom: 5px;
  }
  .login-card .subtitle {
    font-size: 13.5px; color: var(--muted); margin-bottom: 24px;
  }
  .alert {
    display: none; align-items: flex-start; gap: 9px;
    padding: 11px 13px; border-radius: 10px;
    font-size: 13px; line-height: 1.5; margin-bottom: 16px;
  }
  .alert.show { display: flex; }
  .alert.error {
    background: #fef2f2; border: 1px solid #fecaca; color: #b91c1c;
  }
  .alert.error svg { color: var(--danger); flex-shrink: 0; margin-top: 1px; }

  .field { margin-bottom: 16px; }
  .field label {
    display: block; font-size: 12.5px; font-weight: 600;
    color: #374151; margin-bottom: 6px;
  }
  .input-box { position: relative; }
  .input-box .lead {
    position: absolute; left: 13px; top: 50%;
    transform: translateY(-50%);
    width: 17px; height: 17px;
    color: #9ca3af; pointer-events: none;
    transition: color 0.2s;
  }
  .input-box input {
    width: 100%;
    padding: 12px 42px 12px 40px;
    font-size: 14px; font-family: inherit;
    color: var(--ink); background: #fff;
    border: 1.5px solid #e5e7eb;
    border-radius: 10px; outline: none;
    transition: all 0.2s; font-weight: 500;
  }
  .input-box input::placeholder { color: #9ca3af; font-weight: 400; }
  .input-box input:focus {
    border-color: var(--primary);
    box-shadow: 0 0 0 4px rgba(230, 57, 70, 0.1);
  }
  .input-box input:focus ~ .lead { color: var(--primary); }
  .btn-eye {
    position: absolute; right: 6px; top: 50%;
    transform: translateY(-50%);
    width: 30px; height: 30px; border-radius: 7px;
    border: none; background: transparent;
    color: #9ca3af; cursor: pointer;
    display: grid; place-items: center;
    transition: all 0.15s;
  }
  .btn-eye:hover { color: var(--primary); background: #fef2f2; }

  .remember {
    display: inline-flex; align-items: center; gap: 8px;
    cursor: pointer; font-size: 13px; color: #4b5563;
    margin-bottom: 20px; user-select: none;
  }
  .remember input { position: absolute; opacity: 0; pointer-events: none; }
  .remember .box {
    width: 17px; height: 17px; border-radius: 4px;
    border: 1.5px solid #d1d5db;
    display: grid; place-items: center;
    transition: all 0.2s; background: #fff;
  }
  .remember .box svg {
    width: 10px; height: 10px; color: #fff;
    opacity: 0; transform: scale(0.6); transition: all 0.2s;
  }
  .remember input:checked + .box {
    background: var(--primary); border-color: var(--primary);
  }
  .remember input:checked + .box svg { opacity: 1; transform: scale(1); }

  .btn-submit {
    width: 100%; padding: 13px;
    font-size: 14.5px; font-weight: 600; font-family: inherit;
    color: #fff;
    background: linear-gradient(135deg, var(--primary-2), var(--primary-dark));
    border: none; border-radius: 10px;
    cursor: pointer; transition: all 0.25s;
    box-shadow: 0 5px 16px rgba(230, 57, 70, 0.32);
    display: flex; align-items: center; justify-content: center;
    gap: 8px;
  }
  .btn-submit:hover:not(:disabled) {
    transform: translateY(-1px);
    box-shadow: 0 8px 22px rgba(230, 57, 70, 0.42);
  }
  .btn-submit:disabled { cursor: not-allowed; opacity: 0.9; }
  .spinner {
    width: 15px; height: 15px;
    border: 2px solid rgba(255,255,255,0.35);
    border-top-color: #fff; border-radius: 50%;
    animation: spin 0.7s linear infinite; display: none;
  }
  .btn-submit.loading .spinner { display: block; }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* ================= DASHBOARD ================= */
  .dash {
    flex: 1; max-width: 1000px;
    width: 100%; margin: 0 auto;
    padding: 20px;
    display: flex; flex-direction: column;
    gap: 16px;
  }
  .welcome-card {
    background: linear-gradient(135deg, var(--primary-2), var(--primary-dark));
    color: #fff; padding: 24px 26px;
    border-radius: 18px;
    display: flex; align-items: center; gap: 16px;
    box-shadow: 0 10px 26px rgba(230, 57, 70, 0.28);
    position: relative; overflow: hidden;
  }
  .welcome-card::after {
    content: ''; position: absolute;
    width: 220px; height: 220px; border-radius: 50%;
    background: rgba(255, 255, 255, 0.15);
    top: -90px; right: -70px;
  }
  .welcome-avatar {
    width: 62px; height: 62px; border-radius: 16px;
    background: rgba(255, 255, 255, 0.22);
    display: grid; place-items: center;
    font-size: 24px; font-weight: 800;
    font-family: 'Space Grotesk', sans-serif;
    border: 2px solid rgba(255, 255, 255, 0.3);
    flex-shrink: 0; position: relative; z-index: 1;
    text-transform: uppercase;
  }
  .welcome-info { position: relative; z-index: 1; min-width: 0; }
  .welcome-info .greet {
    font-size: 12px; opacity: 0.85; margin-bottom: 1px; font-weight: 500;
  }
  .welcome-info h2 {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 20px; font-weight: 700; margin-bottom: 4px;
    letter-spacing: -0.3px;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    max-width: 100%;
  }
  .level-badge {
    display: inline-flex; align-items: center; gap: 5px;
    padding: 3px 10px;
    background: linear-gradient(135deg, #ffb703, #ff8c00);
    border-radius: 999px;
    font-size: 11px; font-weight: 700;
    color: #1a1f2e;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .stats-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 14px;
  }
  .stat-card {
    background: #fff; border-radius: 16px;
    padding: 18px 18px 16px;
    border: 1px solid var(--line);
    box-shadow: var(--shadow-md);
    border-left: 4px solid var(--primary);
    position: relative;
  }
  .stat-card.vin { border-left-color: var(--primary); }
  .stat-card.xu { border-left-color: var(--gold); }
  .stat-card.vip { border-left-color: var(--accent); }
  .stat-label {
    display: flex; align-items: center; gap: 6px;
    font-size: 11px; color: var(--muted);
    font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.5px; margin-bottom: 10px;
  }
  .stat-label svg { width: 13px; height: 13px; }
  .stat-card.vin .stat-label svg { color: var(--primary); }
  .stat-card.xu .stat-label svg { color: var(--gold); }
  .stat-card.vip .stat-label svg { color: var(--accent); }
  .stat-value {
    font-family: 'Space Grotesk', sans-serif;
    font-size: clamp(22px, 2.8vw, 30px);
    font-weight: 700; color: var(--ink);
    letter-spacing: -0.5px;
    display: flex; align-items: center; gap: 8px;
    word-break: break-all;
  }
  .stat-unit {
    font-size: 12px; font-weight: 600;
    color: var(--muted); margin-left: 4px;
  }
  .stat-value .hide-toggle {
    background: none; border: none;
    color: var(--muted); cursor: pointer;
    padding: 3px; display: grid; place-items: center;
    border-radius: 5px; transition: all 0.15s;
  }
  .stat-value .hide-toggle:hover { color: var(--primary); background: #fef2f2; }
  .stat-hint {
    margin-top: 6px; font-size: 11.5px; color: var(--muted);
  }

  .info-card {
    background: #fff; border-radius: 16px;
    padding: 20px 22px;
    border: 1px solid var(--line);
    box-shadow: var(--shadow-md);
  }
  .info-card h3 {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 15px; font-weight: 700;
    color: var(--ink); margin-bottom: 14px;
    display: flex; align-items: center; gap: 8px;
  }
  .info-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
    gap: 10px;
  }
  .info-item {
    padding: 10px 12px;
    background: #f8f9fb;
    border-radius: 9px;
    border: 1px solid #eef0f4;
  }
  .info-key {
    font-size: 10.5px; color: var(--muted);
    font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.4px; margin-bottom: 3px;
  }
  .info-value {
    font-size: 13px; color: var(--ink);
    font-weight: 600; word-break: break-all;
  }
  .info-value.mono {
    font-family: 'Consolas', 'Monaco', monospace;
    font-size: 12px;
  }
  .info-value.ok { color: var(--success); }
  .info-value.warn { color: var(--danger); }
  .info-value.muted { color: var(--muted); font-style: italic; font-weight: 500; }

  .reveal-btn {
    background: none; border: 1px solid var(--line);
    padding: 3px 8px; border-radius: 6px;
    font-size: 11px; font-weight: 600;
    color: var(--muted); cursor: pointer;
    font-family: inherit; margin-left: 6px;
    transition: all 0.15s;
  }
  .reveal-btn:hover { color: var(--primary); border-color: var(--primary); }

  details.raw-data {
    background: #1a1f2e;
    border-radius: 12px;
    padding: 14px 18px;
    color: #a8b3d0;
    border: 1px solid rgba(255, 255, 255, 0.06);
  }
  details.raw-data summary {
    cursor: pointer; font-weight: 600; color: #fff;
    font-size: 13px; list-style: none;
    display: flex; align-items: center; gap: 8px;
    user-select: none;
  }
  details.raw-data summary::-webkit-details-marker { display: none; }
  details.raw-data summary::before {
    content: '▸'; display: inline-block;
    transition: transform 0.2s; color: #ffb703;
  }
  details.raw-data[open] summary::before { transform: rotate(90deg); }
  details.raw-data pre {
    margin-top: 12px;
    font-family: 'Consolas', 'Monaco', monospace;
    font-size: 11.5px; white-space: pre-wrap;
    word-break: break-word; color: #e2e8f0;
    max-height: 380px; overflow-y: auto;
  }

  /* ================= FOOTER ================= */
  .footer {
    background: #fff; border-top: 1px solid var(--line);
    padding: 18px 20px; margin-top: auto;
  }
  .footer-inner {
    max-width: 1280px; margin: 0 auto;
    display: flex; flex-wrap: wrap;
    align-items: center; justify-content: space-between;
    gap: 12px;
  }
  .copyright {
    font-size: 12.5px; color: var(--muted);
    display: flex; align-items: center; gap: 5px;
    flex-wrap: wrap;
  }
  .copyright b {
    background: linear-gradient(135deg, var(--primary-2), var(--primary-dark));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text; font-weight: 700;
  }

  /* ================= RESPONSIVE ================= */
  @media (max-width: 900px) {
    .main {
      grid-template-columns: 1fr;
      padding: 18px 16px; gap: 20px;
    }
    .brand-panel {
      min-height: auto;
      padding: 28px 24px;
      border-radius: 16px;
    }
    .feature-list { display: none; }
    .brand-panel h1 { font-size: 22px; margin: 14px 0 10px; }
    .brand-panel p.lead { font-size: 13.5px; }
  }
  @media (max-width: 720px) {
    .stats-grid { grid-template-columns: 1fr; }
    .welcome-card { padding: 20px; gap: 14px; }
    .welcome-avatar { width: 52px; height: 52px; font-size: 20px; }
    .welcome-info h2 { font-size: 17px; }
    .login-card { padding: 30px 22px 26px; }
    .login-card h2 { font-size: 20px; }
  }
  @media (max-width: 480px) {
    .header-inner { padding: 10px 14px; }
    .user-chip span { display: none; }
    .user-chip { padding: 4px; }
    .brand-name small { font-size: 9px; letter-spacing: 1.4px; }
    .dash { padding: 14px; gap: 12px; }
    .stat-card { padding: 14px 16px; }
    .stat-value { font-size: 22px; }
  }
</style>
</head>
<body>

<!-- ================== LOGIN VIEW ================== -->
<div id="loginView">
  <header class="header">
    <div class="header-inner">
      <a href="#" class="brand">
        <div class="brand-mark">LC79</div>
        <div class="brand-name">
          <strong>AUTO CƯỢC LC79</strong>
          <small>Automation System</small>
        </div>
      </a>
    </div>
  </header>

  <main class="main">
    <section class="brand-panel">
      <div>
        <div class="badge-new"><span class="dot"></span>Hệ thống đang hoạt động ổn định</div>
        <h1>Đăng nhập để bước vào<br><span class="grad">kỷ nguyên tự động hóa</span></h1>
        <p class="lead">
          Nền tảng quản lý tài khoản và tự động hóa chuyên nghiệp — kiểm soát số dư, VIP và toàn bộ thông tin tài khoản chỉ trong một giao diện.
        </p>
        <div class="feature-list">
          <div class="feature-item">
            <div class="feature-icon">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
            </div>
            <div><strong>Bảo mật MD5</strong><small>Mật khẩu được mã hóa 1 chiều</small></div>
          </div>
          <div class="feature-item">
            <div class="feature-icon">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
            </div>
            <div><strong>Kết nối API trực tiếp</strong><small>Đồng bộ dữ liệu thời gian thực</small></div>
          </div>
          <div class="feature-item">
            <div class="feature-icon">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
            </div>
            <div><strong>Dashboard cá nhân</strong><small>VIN, XU, VIP, Level đầy đủ</small></div>
          </div>
        </div>
      </div>
    </section>

    <section class="login-panel">
      <div class="login-card">
        <h2>Chào mừng trở lại 👋</h2>
        <p class="subtitle">Đăng nhập tài khoản để tiếp tục</p>

        <div class="alert error" id="alertBox">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          <span id="alertText"></span>
        </div>

        <form id="loginForm" autocomplete="off" novalidate>
          <div class="field">
            <label for="username">Tên đăng nhập</label>
            <div class="input-box">
              <input type="text" id="username" name="username" placeholder="Nhập tên đăng nhập" autocomplete="username" required />
              <svg class="lead" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
            </div>
          </div>

          <div class="field">
            <label for="password">Mật khẩu</label>
            <div class="input-box">
              <input type="password" id="password" name="password" placeholder="Nhập mật khẩu" autocomplete="current-password" required />
              <svg class="lead" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
              <button type="button" class="btn-eye" id="togglePass" aria-label="Hiện/ẩn mật khẩu">
                <svg id="eyeIcon" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
              </button>
            </div>
          </div>

          <label class="remember">
            <input type="checkbox" id="remember" />
            <span class="box">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
            </span>
            Ghi nhớ đăng nhập
          </label>

          <button type="submit" class="btn-submit" id="btnLogin">
            <span class="spinner"></span>
            <span class="btn-text">Đăng nhập</span>
          </button>
        </form>
      </div>
    </section>
  </main>

  <footer class="footer">
    <div class="footer-inner">
      <div class="copyright">© 2025 AUTO CƯỢC LC79 — Bản quyền thuộc về <b>HuyDaiXuVN</b></div>
    </div>
  </footer>
</div>

<!-- ================== DASHBOARD VIEW ================== -->
<div id="dashboardView" style="display:none">
  <header class="header">
    <div class="header-inner">
      <a href="#" class="brand">
        <div class="brand-mark">LC79</div>
        <div class="brand-name">
          <strong>AUTO CƯỢC LC79</strong>
          <small>Dashboard</small>
        </div>
      </a>
      <div class="header-right">
        <div class="user-chip">
          <div class="avatar" id="userAvatar">U</div>
          <span id="userChipName">User</span>
        </div>
        <button class="btn-logout" id="btnLogout">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
          Đăng xuất
        </button>
      </div>
    </div>
  </header>

  <main class="dash">
    <!-- Welcome -->
    <div class="welcome-card">
      <div class="welcome-avatar" id="welcomeAvatar">U</div>
      <div class="welcome-info">
        <div class="greet">Xin chào, chào mừng trở lại!</div>
        <h2 id="welcomeName">nickname</h2>
        <span class="level-badge" id="levelBadge">★ LV.1</span>
      </div>
    </div>

    <!-- Stats -->
    <div class="stats-grid">
      <div class="stat-card vin">
        <div class="stat-label">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
          Số dư VIN
        </div>
        <div class="stat-value">
          <span id="vinValue">—</span><span class="stat-unit">VIN</span>
          <button class="hide-toggle" data-target="vinValue" title="Ẩn/hiện">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
          </button>
        </div>
        <div class="stat-hint">Đơn vị tiền tệ chính</div>
      </div>

      <div class="stat-card xu">
        <div class="stat-label">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v10M9 10h6M9 14h6"/></svg>
          Số dư XU
        </div>
        <div class="stat-value">
          <span id="xuValue">—</span><span class="stat-unit">XU</span>
          <button class="hide-toggle" data-target="xuValue" title="Ẩn/hiện">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
          </button>
        </div>
        <div class="stat-hint">Đơn vị phụ</div>
      </div>

      <div class="stat-card vip">
        <div class="stat-label">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
          VIP Point
        </div>
        <div class="stat-value">
          <span id="vipValue">—</span><span class="stat-unit">điểm</span>
        </div>
        <div class="stat-hint" id="vipHint">Điểm tích lũy thành viên</div>
      </div>
    </div>

    <!-- Info -->
    <div class="info-card">
      <h3>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
        Thông tin tài khoản
      </h3>
      <div class="info-grid" id="infoGrid"></div>
    </div>

    <!-- Raw -->
    <details class="raw-data">
      <summary>Xem dữ liệu thô từ API (debug)</summary>
      <pre id="rawData">—</pre>
    </details>
  </main>

  <footer class="footer">
    <div class="footer-inner">
      <div class="copyright">© 2025 AUTO CƯỢC LC79 — Bản quyền thuộc về <b>HuyDaiXuVN</b></div>
    </div>
  </footer>
</div>

<script>
const API_ENDPOINT = '/api/login';

/* =========================================================
   🔒 CHỐNG ZOOM TOÀN DIỆN
   ========================================================= */
let lastTouch = 0;
document.addEventListener('touchend', (e) => {
  const now = Date.now();
  if (now - lastTouch <= 300) e.preventDefault();
  lastTouch = now;
}, { passive: false });

['gesturestart', 'gesturechange', 'gestureend'].forEach(ev => {
  document.addEventListener(ev, e => e.preventDefault(), { passive: false });
});

document.addEventListener('wheel', (e) => {
  if (e.ctrlKey) e.preventDefault();
}, { passive: false });

document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && ['+', '-', '=', '0'].includes(e.key)) {
    e.preventDefault();
  }
});

document.addEventListener('touchmove', (e) => {
  if (e.touches.length > 1) e.preventDefault();
}, { passive: false });

/* =========================================================
   HELPERS
   ========================================================= */
const $ = id => document.getElementById(id);

function showError(msg) {
  $('alertText').textContent = msg;
  $('alertBox').classList.add('show');
}
function hideError() { $('alertBox').classList.remove('show'); }

function formatNumber(v) {
  if (v === null || v === undefined || v === '') return '0';
  const n = Number(v);
  if (isNaN(n)) return String(v);
  return new Intl.NumberFormat('vi-VN').format(n);
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function decodeSessionKey(sk) {
  if (!sk) return null;
  try {
    const json = atob(sk);
    return JSON.parse(json);
  } catch (e) {
    console.error('[DECODE sessionKey]', e);
    return null;
  }
}

function isLoginSuccess(d) {
  return d && d.success === true && String(d.errorCode) === '0' && !!d.sessionKey;
}

/* =========================================================
   HIỆN/ẨN MẬT KHẨU
   ========================================================= */
const eyeOpen = `<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>`;
const eyeClosed = `<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/>`;
$('togglePass').addEventListener('click', () => {
  const pw = $('password');
  const show = pw.type === 'password';
  pw.type = show ? 'text' : 'password';
  $('eyeIcon').innerHTML = show ? eyeClosed : eyeOpen;
});

/* =========================================================
   ĐĂNG NHẬP & XỬ LÝ GIAO DIỆN DASHBOARD
   ========================================================= */
const savedUser = localStorage.getItem('lc79_user');
if (savedUser) {
  $('username').value = savedUser;
  $('remember').checked = true;
}

$('loginForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  hideError();

  const username = $('username').value.trim();
  const password = $('password').value;

  if (!username || !password) {
    showError('Vui lòng nhập đầy đủ tên đăng nhập và mật khẩu.');
    return;
  }

  // Mã hóa mật khẩu MD5 (sử dụng CryptoJS đã include)
  const passwordMd5 = CryptoJS.MD5(password).toString();

  const btn = $('btnLogin');
  btn.classList.add('loading');
  btn.disabled = true;

  try {
    const res = await fetch(API_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password: passwordMd5 })
    });
    
    const data = await res.json();

    if (isLoginSuccess(data)) {
      if ($('remember').checked) {
        localStorage.setItem('lc79_user', username);
      } else {
        localStorage.removeItem('lc79_user');
      }

      // Hiển thị Dashboard và ẩn Login
      $('loginView').style.display = 'none';
      $('dashboardView').style.display = 'block';

      // Giải mã sessionKey (Base64 chứa JSON thô thực tế)
      const parsedData = decodeSessionKey(data.sessionKey) || {};
      
      const nick = parsedData.nickname || username;
      const initial = nick.charAt(0).toUpperCase();

      $('userAvatar').textContent = initial;
      $('userChipName').textContent = nick;
      $('welcomeAvatar').textContent = initial;
      $('welcomeName').textContent = nick;
      
      // Ánh xạ dữ liệu thực tế từ sessionKey trả về
      $('vinValue').textContent = formatNumber(parsedData.vinTotal || 0);
      $('xuValue').textContent = formatNumber(parsedData.xuTotal || 0);
      $('vipValue').textContent = formatNumber(parsedData.vippoint || 0);
      $('levelBadge').textContent = `★ LV.${data.curLevel || 1}`;

      // Bảng thông tin tài khoản chi tiết
      const infoGrid = $('infoGrid');
      infoGrid.innerHTML = `
        <div class="info-item"><div class="info-key">Tên nhân vật</div><div class="info-value mono">${escapeHtml(parsedData.nickname || 'N/A')}</div></div>
        <div class="info-item"><div class="info-key">Địa chỉ IP</div><div class="info-value mono">${escapeHtml(parsedData.ipAddress || 'N/A')}</div></div>
        <div class="info-item"><div class="info-key">Ngày tạo</div><div class="info-value mono">${escapeHtml(parsedData.createTime || 'N/A')}</div></div>
        <div class="info-item"><div class="info-key">Cấp độ (Level)</div><div class="info-value ok">${escapeHtml(data.curLevel || 1)}</div></div>
      `;

      $('rawData').textContent = JSON.stringify(data, null, 2);

    } else {
      showError(data.message || 'Đăng nhập thất bại, vui lòng kiểm tra lại thông tin.');
    }
  } catch (err) {
    console.error(err);
    showError('Không thể kết nối đến máy chủ API.');
  } finally {
    btn.classList.remove('loading');
    btn.disabled = false;
  }
});

// Đăng xuất
$('btnLogout').addEventListener('click', () => {
  $('dashboardView').style.display = 'none';
  $('loginView').style.display = 'block';
  $('password').value = '';
  hideError();
});

// Ẩn hiện số dư
document.querySelectorAll('.hide-toggle').forEach(btn => {
  btn.addEventListener('click', () => {
    const targetId = btn.getAttribute('data-target');
    const el = $(targetId);
    if (el.textContent === '••••••') {
      el.textContent = el.dataset.value || '0';
    } else {
      el.dataset.value = el.textContent;
      el.textContent = '••••••';
    }
  });
});
</script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json
    username = data.get('username')
    password_md5 = data.get('password') # Chuỗi đã mã hóa MD5 từ giao diện gửi lên
    
    # URL API thực tế theo yêu cầu
    target_url = "https://apifo88daigia.tele68.com/api"
    
    # Các tham số query chuẩn theo cấu trúc mẫu
    params = {
        "c": 3,
        "un": username,
        "pw": password_md5,
        "cp": "R",
        "cl": "R",
        "pf": "web"
    }
    
    try:
        # Gọi request thật đến API external
        response = requests.get(target_url, params=params, timeout=10)
        api_result = response.json()
        return jsonify(api_result)
    except Exception as e:
        return jsonify({
            "success": False,
            "errorCode": "-1",
            "message": f"Lỗi kết nối API: {str(e)}"
        })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)