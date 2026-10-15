const http = require('http');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright-core');

const PORT = process.env.CBN_PORT ? parseInt(process.env.CBN_PORT) : 8787;
const CHROME = process.env.CBN_CHROME || '/usr/bin/chromium';
const JSDIR = path.join(__dirname, 'web');

// ---------- 密钥 ----------
function loadKeys() {
  let pub = null, priv = null;
  for (const f of fs.readdirSync(JSDIR)) {
    const p = path.join(JSDIR, f);
    if (!fs.statSync(p).isFile()) continue;
    const t = fs.readFileSync(p, 'utf8');
    for (const m of t.matchAll(/"(MII[A-Za-z0-9+/=]{60,})"/g)) {
      const k = m[1];
      if (k.length === 392) pub = k;
      if (k.length > 700) priv = k;
    }
  }
  if (!pub || !priv) throw new Error('未能从 JS 载入密钥');
  return { pub, priv };
}

const { pub: PUB_B64, priv: PRIV_B64 } = loadKeys();
const pubKey = crypto.createPublicKey({ key: Buffer.from(PUB_B64, 'base64'), format: 'der', type: 'spki' });
const privKey = crypto.createPrivateKey({ key: Buffer.from(PRIV_B64, 'base64'), format: 'der', type: 'pkcs8' });

const CHANNEL_ID = 'cd_20220516_093342';
const API_V = '1.1.7.0915_release';
const ORIGIN = 'https://www.10099.com.cn';

// ---------- 加密 ----------
function encryptLong(pt, key) {
  const k = 256, limit = k - 12;
  const chunks = []; let start = 0, cur = 0;
  for (let i = 0; i < pt.length; i++) {
    const c = pt.charCodeAt(i);
    const clen = c <= 127 ? 1 : c <= 2047 ? 2 : c <= 65535 ? 3 : 4;
    cur += clen;
    if (cur > limit) { chunks.push(pt.substring(start, i)); start = i; cur = clen; }
  }
  chunks.push(pt.substring(start));
  return Buffer.concat(chunks.map(ch =>
    crypto.publicEncrypt({ key, padding: crypto.constants.RSA_PKCS1_PADDING }, Buffer.from(ch, 'utf8'))
  )).toString('base64');
}

function decryptLong(b64) {
  const raw = Buffer.from(b64, 'base64');
  const out = [];
  for (let i = 0; i < raw.length; i += 256) {
    const blk = raw.subarray(i, i + 256);
    if (blk.length < 256) break;
    out.push(crypto.privateDecrypt({ key: privKey, padding: crypto.constants.RSA_PKCS1_PADDING }, blk));
  }
  return Buffer.concat(out).toString('utf8');
}

function makeSign(o) {
  const conv = (o, nested = false) => {
    if (!o || typeof o !== 'object' || Array.isArray(o)) return '';
    const out = [];
    for (const k of Object.keys(o).sort()) {
      const v = o[k];
      if (v && typeof v === 'object' && !Array.isArray(v) && !nested) out.push(`${k}=${conv(v, true)}`);
      else if (v !== null && v !== undefined && v !== '' && typeof v !== 'object') out.push(`${k}=${v}`);
    }
    return out.join('&');
  };
  return crypto.createHash('md5').update(conv(o)).digest('hex');
}

// ---------- 浏览器会话 ----------
let _browser = null, _ctx = null, _page = null, _ready = false;
let _lastUse = 0;
const IDLE_MS = 5 * 60 * 1000;   // 5 分钟无请求自动关闭浏览器，省内存

async function ensureBrowser() {
  if (_ready && _page) { _lastUse = Date.now(); return; }
  const launchOpts = {
    executablePath: CHROME,
    headless: true,
    timeout: 90000,
    args: [
      '--disable-blink-features=AutomationControlled',
      '--no-sandbox',
      '--disable-dev-shm-usage',
    ],
  };
  // 3GB 以内内存的机器（如小容量树莓派）可加 --single-process 省内存，
  // 但它会在部分 ARM Chromium 上卡死，默认不加。
  if (process.env.CBN_LOWMEM === '1') {
    launchOpts.args.push('--single-process', '--no-zygote');
  }
  _browser = await chromium.launch(launchOpts);
  _ctx = await _browser.newContext({
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36',
    ignoreHTTPSErrors: true,
  });
  _page = await _ctx.newPage();
  await _page.goto(ORIGIN + '/login.html',
                   { waitUntil: 'networkidle', timeout: 60000 }).catch(() => {});
  await _page.waitForTimeout(3000);
  _ready = true;
  _lastUse = Date.now();
  console.log('[browser] ready');
}

async function closeBrowser() {
  try { if (_browser) await _browser.close(); } catch (e) {}
  _browser = _ctx = _page = null;
  _ready = false;
  console.log('[browser] closed (idle)');
}

setInterval(() => {
  if (_ready && Date.now() - _lastUse > IDLE_MS) closeBrowser();
}, 60000);

async function callApi(apiPath, params, method = 'POST') {
  await ensureBrowser();

  if (method === 'GET') {
    // 注意：验证码是二进制 JPEG，用 evaluate 传 base64 会因体积大而变慢/超时。
    // 改用 Playwright 的 request API 直接拿，复用页面 cookie。
    const cookies = await _ctx.cookies();
    const cookieHeader = cookies.map(c => `${c.name}=${c.value}`).join('; ');
    const resp = await _ctx.request.get(ORIGIN + '/contact-web/api' + apiPath, {
      headers: {
        'Cookie': cookieHeader,
        'Referer': ORIGIN + '/login.html',
        'X-Requested-With': 'XMLHttpRequest',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36',
      },
      timeout: 60000,
    });
    const ct = resp.headers()['content-type'] || '';
    const buf = await resp.body();
    if (ct.includes('image')) {
      return { _image: true, contentType: ct, buf };
    }
    return { _text: buf.toString('utf8') };
  }

  const p = { ...params, channelId: CHANNEL_ID, v: API_V, timestamp: Date.now() };
  const body = { data: encryptLong(encodeURIComponent(JSON.stringify(p)), pubKey) };
  const access = makeSign(p);

  const res = await _page.evaluate(async ([apiPath, body, access]) => {
    const r = await fetch('/contact-web/api' + apiPath, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Access': access,
                 'X-Requested-With': 'XMLHttpRequest',
                 'Accept': 'application/json, text/javascript, */*; q=0.01' },
      body: JSON.stringify(body), credentials: 'include',
    });
    return { status: r.status, text: await r.text() };
  }, [apiPath, body, access]);

  if (res.text.includes('aliyun_waf') || res.text.includes('renderData')) {
    console.log('[waf] challenge, reloading...');
    await closeBrowser();
    await ensureBrowser();
    return callApi(apiPath, params, method);
  }

  let json;
  try { json = JSON.parse(res.text); }
  catch (e) { return { _httpStatus: res.status, _raw: res.text.slice(0, 500) }; }

  // 响应体加密则解密
  if (typeof json.data === 'string' && json.data.length > 80) {
    try { json.data = JSON.parse(decodeURIComponent(decryptLong(json.data))); } catch (e) {}
  }
  return json;
}

// ---------- HTTP ----------
function readBody(req) {
  return new Promise((resolve) => {
    let d = '';
    req.on('data', c => d += c);
    req.on('end', () => { try { resolve(d ? JSON.parse(d) : {}); } catch { resolve({}); } });
  });
}

function sendJson(res, code, obj) {
  const s = JSON.stringify(obj);
  res.writeHead(code, { 'Content-Type': 'application/json; charset=utf-8',
                        'Content-Length': Buffer.byteLength(s) });
  res.end(s);
}

function sendImage(res, buf, ct) {
  const b = Buffer.isBuffer(buf) ? buf : Buffer.from(buf);
  res.writeHead(200, { 'Content-Type': ct || 'image/jpeg',
                       'Content-Length': b.length,
                       'Cache-Control': 'no-store' });
  res.end(b);
}

const server = http.createServer(async (req, res) => {
  const url = req.url.split('?')[0];
  try {
    // --- GET 路由 ---
    if (req.method === 'GET') {
      if (url === '/health') {
        return sendJson(res, 200, { ok: true, browser: _ready });
      }
      if (url === '/captcha') {
        const r = await callApi('/login/getImageCheckCode', {}, 'GET');
        if (r._image) return sendImage(res, r.buf, r.contentType);
        return sendJson(res, 502, { error: 'captcha failed', detail: r });
      }
      return sendJson(res, 404, { error: 'not found', path: url });
    }

    if (req.method !== 'POST') return sendJson(res, 405, { error: 'method not allowed' });

    const body = await readBody(req);
    let out;

    switch (url) {
      // 发短信（须在取图形验证码之后调用；发短信不消耗验证码）
      case '/send_code':
        out = await callApi('/login/getVerifyCode', { recieveNum: body.phone, type: 5 });
        break;

      // 3) 登录（图形码 + 短信码）
      case '/login':
        out = await callApi('/login/gwLogin', {
          loginPhone: body.phone,
          loginPassWord: body.code,
          loginType: '5',
          channelType: '1',
          imageCheckCode: body.image_code || '',
        });
        break;

      case '/flow':
        out = await callApi('/busi/qryUserRes',
                            { sessionId: body.sessionId, accessNum: body.accessNum });
        break;

      case '/balance':
        out = await callApi('/busi/qryBalanceFee',
                            { sessionId: body.sessionId, accessNum: body.accessNum });
        break;

      case '/bill':
        out = await callApi('/busi/qryBillInfo',
                            { sessionId: body.sessionId, accessNum: body.accessNum });
        break;

      case '/pack':
        out = await callApi('/busi/qryPhonePackInfo',
                            { sessionId: body.sessionId, accessNum: body.accessNum });
        break;

      default:
        return sendJson(res, 404, { error: 'not found', path: url });
    }
    return sendJson(res, 200, out);
  } catch (e) {
    console.error('[error]', e);
    return sendJson(res, 500, { error: String((e && e.message) || e) });
  }
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`中国广电代理服务已启动: http://127.0.0.1:${PORT}`);
  console.log('  GET  /captcha                  取图形验证码图片');
  console.log('  POST /send_code  {phone}       发送短信验证码');
  console.log('  POST /login      {phone, code, image_code}');
  console.log('  POST /flow       {sessionId, accessNum}');
  console.log('  POST /balance    {sessionId, accessNum}');
  console.log('  GET  /health');
});

process.on('SIGINT', async () => {
  await closeBrowser();
  process.exit(0);
});
