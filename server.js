/**
 * 努努排版小工具 · 本地服务
 * 作用：
 *   1. 把项目目录作为静态站点提供（index.html / assets/*）
 *   2. 提供色卡数据接口 GET /api/palette —— 数据唯一来源 data/palette.json
 *
 * 启动：node server.js   然后打开 http://localhost:5179
 * 说明：色卡是固定数据，接口只读；用不到登录 / 数据库。
 */
const http = require('http');
const fs = require('fs');
const path = require('path');

const ROOT = __dirname;
const PORT = Number(process.env.PORT) || 5179;
/* 每个厂家一份色卡数据：接口路径 → 数据文件 */
const PALETTE_ROUTES = {
  '/api/palette': path.join(ROOT, 'data', 'palette.json'),   // 义乌思博尔
  '/api/palette2': path.join(ROOT, 'data', 'palette2.json')  // 紫誉 / 大狮子布艺
};

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.png': 'image/png',
  '.webp': 'image/webp',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon'
};

function sendJson(res, code, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(code, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(body),
    'cache-control': 'no-store'
  });
  res.end(body);
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://' + (req.headers.host || 'localhost'));
  const pathname = decodeURIComponent(url.pathname);

  // 色卡接口（只读）
  if (PALETTE_ROUTES[pathname]) {
    const file = PALETTE_ROUTES[pathname];
    const rel = path.relative(ROOT, file);
    if (req.method !== 'GET') {
      sendJson(res, 405, { error: '色卡数据为固定内容，只支持 GET' });
      return;
    }
    fs.readFile(file, (err, buf) => {
      if (err) {
        sendJson(res, 500, { error: '读不到 ' + rel });
        return;
      }
      try {
        const data = JSON.parse(buf.toString('utf8'));
        sendJson(res, 200, data);
      } catch (e) {
        sendJson(res, 500, { error: rel + ' 格式不是合法 JSON' });
      }
    });
    return;
  }

  if (pathname === '/api/health') {
    sendJson(res, 200, { ok: true, palettes: PALETTE_ROUTES });
    return;
  }

  // 静态文件
  let rel = pathname === '/' ? '/index.html' : pathname;
  const file = path.normalize(path.join(ROOT, rel));
  if (!file.startsWith(ROOT)) {
    res.writeHead(403, { 'content-type': 'text/plain; charset=utf-8' });
    res.end('403 Forbidden');
    return;
  }
  fs.readFile(file, (err, buf) => {
    if (err) {
      res.writeHead(404, { 'content-type': 'text/plain; charset=utf-8' });
      res.end('404 Not Found');
      return;
    }
    res.writeHead(200, {
      'content-type': MIME[path.extname(file).toLowerCase()] || 'application/octet-stream',
      'content-length': buf.length,
      'cache-control': pathname.startsWith('/assets/') ? 'public, max-age=86400' : 'no-cache'
    });
    res.end(buf);
  });
});

server.listen(PORT, () => {
  console.log('努努排版小工具已启动');
  console.log('  页面:      http://localhost:' + PORT + '/');
  Object.keys(PALETTE_ROUTES).forEach(p => console.log('  色卡接口:  http://localhost:' + PORT + p));
});
