/**
 * 构建「小红书小工具」离线 zip 产物（dist/）
 * 依据 .skill/minitool-zip-builder 的规范改造 index.html：
 *   1. 内联 <script> 外置为 app.js（容器 CSP 禁止内联脚本 / 行内事件）
 *   2. 移除 fetch（容器不联网），色卡只读包内 seed
 *   3. a[download] 导出改为容器 saveImageToPhotosAlbum，低版本页内展示 + 提示截图
 *   4. 可选链降级到 ES2017（Chrome 61 基线）
 *   5. CSS：grid-gap 基线、flex gap 行为检测回退、安全区与滚动
 *   6. 色卡照片按展示尺寸重压缩，控制包体
 * 用法：node tools/build-minitool.js
 */
const fs = require('fs');
const path = require('path');
const jpeg = require('./vendor/jpeg-js');

const ROOT = path.join(__dirname, '..');
const DIST = path.join(ROOT, 'dist');
const PHOTO_W = 800;   // 色块展示约 60px，sprite 放大后 800px 宽足够
const PHOTO_Q = 72;

function resetDir(d) {
  fs.rmSync(d, { recursive: true, force: true });
  fs.mkdirSync(d, { recursive: true });
}

/* ---------- 1. 拆 index.html ---------- */
let html = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');

// 抽出内联主脚本（最后一个裸 <script> ... </script>）
const m = html.match(/<script>\n([\s\S]*?)\n<\/script>/);
if (!m) throw new Error('找不到内联主脚本');
let js = m[1];
html = html.replace(/<script>\n[\s\S]*?\n<\/script>/, '<script src="./app.js"></script>');

/* ---------- 2. index.html：viewport / 脚本路径 / CSS 基线层 ---------- */
const vpOld = /<meta name="viewport"[^>]*>/;
const vpNew = '<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">';
if (!vpOld.test(html)) throw new Error('找不到 viewport meta');
html = html.replace(vpOld, vpNew);

html = html.replace(/<script src="assets\//g, '<script src="./assets/');
html = html.replace(/url\('assets\//g, "url('./assets/");

// grid 容器：Chrome 61 认识 grid-gap
['#pagesGrid', '#partGrid', '.swatches'].forEach(sel => {
  html = html.replace(new RegExp('(' + sel.replace('#', '#').replace('.', '\\.') + '\\{[^}]*?)gap:(\\d+)px', 'g'),
    (s, a, b) => a + 'grid-gap:' + b + 'px');
});

const cssFallback = `
/* ---- Chrome 61 基线层（小工具容器最低内核） ---- */
body{padding-top:0;padding-top:var(--safe-area-inset-top,env(safe-area-inset-top,0px));
     padding-bottom:0;padding-bottom:var(--safe-area-inset-bottom,env(safe-area-inset-bottom,0px))}
.swatches{-webkit-overflow-scrolling:touch}
html.no-flex-gap .step-head>*{margin-right:10px}
html.no-flex-gap .seg>*{margin-right:8px;margin-bottom:8px}
html.no-flex-gap .numrow>*{margin-right:10px;margin-bottom:10px}
html.no-flex-gap #previewList>*{margin-right:10px;margin-bottom:10px}
html.no-flex-gap #previewList .thumb>*{margin-right:8px}
html.no-flex-gap .actions>*{margin-right:12px;margin-bottom:12px}
html.no-flex-gap #genBar>*{margin-right:12px;margin-bottom:12px}
html.no-flex-gap #staleBar>*{margin-right:8px}
html.no-flex-gap #bgCustomRow>*{margin-right:10px;margin-bottom:10px}
html.no-flex-gap #partTools>*{margin-right:10px;margin-bottom:10px}
html.no-flex-gap .sw-row>*{margin-right:9px;margin-bottom:9px}
html.no-flex-gap .pal-tabs>*{margin-right:7px;margin-bottom:7px}
html.no-flex-gap .pal-vendors>*{margin-right:14px;margin-bottom:9px}
html.no-flex-gap .pal-tabrow>*{margin-right:8px}
html.no-flex-gap .pal-tab-idx>*{margin-right:5px}
html.no-flex-gap .match-item>*{margin-right:11px}
/* 导出预览层（无容器能力时展示 PNG 供截图保存） */
#shotMask{position:fixed;left:0;top:0;right:0;bottom:0;background:rgba(0,0,0,.72);z-index:99;display:none;
          flex-direction:column;align-items:center;justify-content:center;padding:16px}
#shotMask.on{display:flex}
#shotMask img{max-width:100%;max-height:74vh;background:#fff;border-radius:8px}
#shotMask .tip{color:#fff;font-size:13px;margin:12px 0;line-height:1.5;text-align:center}
</style>`;
html = html.replace(/<\/style>/, cssFallback);

/* ---------- 3. app.js：去掉联网 / 下载，语法降级 ---------- */

// 3.1 可选链 → ES2017
js = js.split('const score=pages.length*1000000 - (pages[pages.length-1]?.items.length||0);').join(
  'const __last=pages[pages.length-1];const score=pages.length*1000000 - ((__last&&__last.items.length)||0);');

// 3.2 loadPalette：不联网，直接读包内 seed
const loadOld = /async function loadPalette\(\)\{[\s\S]*?\n\}/;
const loadNew = `async function loadPalette(){
  /* 容器不联网：色卡全部来自包内 seed 脚本，不做任何 fetch */
  for(const v of palVendors){
    const g=PAL_SEEDS[v.key];
    const raw=(g&&window[g]&&window[g].items)?window[g]:null;
    if(raw&&raw.items.length){
      v.palette=normalizePalette(raw);
      v.pages=buildPages(v.palette.items);
      v.name=vendorName(v);
    }
  }
  palSource=loadedVendors().length?'seed':'none';
}`;
if (!loadOld.test(js)) throw new Error('loadPalette 未匹配');
js = js.replace(loadOld, loadNew);

// 3.3 导出：a[download] → 容器保存图片，低版本页内展示
const dlOld = /function downloadAll\(\)\{[\s\S]*?\n\}/;
const dlNew = `function showShot(dataUrl,title){
  let mask=document.getElementById('shotMask');
  if(!mask){
    mask=document.createElement('div');mask.id='shotMask';
    const im=document.createElement('img');im.id='shotImg';
    const tip=document.createElement('div');tip.className='tip';tip.id='shotTip';
    const btn=document.createElement('button');btn.className='btn primary';btn.textContent='关闭';
    btn.addEventListener('click',()=>mask.classList.remove('on'));
    mask.appendChild(im);mask.appendChild(tip);mask.appendChild(btn);
    document.body.appendChild(mask);
    mask.addEventListener('click',e=>{if(e.target===mask)mask.classList.remove('on');});
  }
  document.getElementById('shotImg').src=dataUrl;
  document.getElementById('shotTip').textContent=title||'当前环境不支持直接保存，请截图保存该图';
  mask.classList.add('on');
}
function miniTool(){ return (window.xhs&&window.xhs.miniTool)||null; }
function saveOne(cv){
  const mt=miniTool();
  const dataUrl=cv.toDataURL('image/png');
  if(mt&&typeof mt.writeTempFile==='function'){
    return mt.writeTempFile({data:dataUrl}).then(function(r){
      const fp=r&&r.filePath;
      if(fp&&typeof mt.saveImageToPhotosAlbum==='function') return mt.saveImageToPhotosAlbum({filePath:fp});
      return Promise.reject(new Error('no saver'));
    });
  }
  if(mt&&typeof mt.saveImageToPhotosAlbum==='function'){
    return mt.saveImageToPhotosAlbum({filePath:dataUrl});
  }
  showShot(dataUrl);
  return Promise.resolve(false);
}
function downloadAll(){
  if(!state.pagesData.length){ toast('暂无结果'); return; }
  const n=state.pagesData.length;
  const mt=miniTool();
  if(!mt) toast('将逐页展示排版图，请截图保存'); else toast('已开始保存 '+n+' 页到相册');
  let i=0;
  (function next(){
    if(i>=n) return;
    const idx=i++;
    const cv=renderPageFull(state.pagesData[idx]);
    setTimeout(function(){
      saveOne(cv).catch(function(){ showShot(cv.toDataURL('image/png')); }).then(next);
    },260);
  })();
}`;
if (!dlOld.test(js)) throw new Error('downloadAll 未匹配');
js = js.replace(dlOld, dlNew);

// 3.4 能力检测：Flex gap 行为检测（Chrome 61 无 flex gap）
js += `
/* ---------- 容器能力检测（Chrome 61 基线 + 增强层） ---------- */
(function(){
  function supportsFlexGap(){
    try{
      var f=document.createElement('div');
      f.style.position='absolute';f.style.visibility='hidden';
      f.style.display='flex';f.style.flexDirection='column';f.style.rowGap='1px';
      f.appendChild(document.createElement('div'));
      f.appendChild(document.createElement('div'));
      document.body.appendChild(f);
      var ok=f.scrollHeight===1;
      f.parentNode.removeChild(f);
      return ok;
    }catch(e){ return false; }
  }
  if(!supportsFlexGap()) document.documentElement.classList.add('no-flex-gap');
})();
`;

/* ---------- 4. 输出 dist（全部平铺到根目录，不使用子目录） ---------- */
resetDir(DIST);

// index.html：脚本与资源引用去掉 assets/ 前缀
html = html.replace(/<script src="\.\/assets\//g, '<script src="./');
html = html.replace(/url\('\.\/assets\//g, "url('./");

// app.js 内若直接写了 assets/ 前缀（含注释），同样去掉
js = js.replace(/'\.\/assets\//g, "'./").replace(/"\.\/assets\//g, '"./')
       .replace(/assets\/(palette-seed)/g, '$1');

fs.writeFileSync(path.join(DIST, 'index.html'), html);
fs.writeFileSync(path.join(DIST, 'app.js'), js);

// seed 数据脚本：复制到根目录，并把内部的 photos 路径改为平铺路径
['palette-seed.js', 'palette-seed2.js', 'palette-seed3.js'].forEach(f => {
  const src = fs.readFileSync(path.join(ROOT, 'assets', f), 'utf8')
    .replace(/"assets\//g, '"').replace(/'assets\//g, "'");
  fs.writeFileSync(path.join(DIST, f), src);
});

/* ---------- 5. 色卡照片按展示尺寸重压缩 ---------- */
function resizeJpeg(buf, tw, q) {
  const img = jpeg.decode(buf, { useTArray: true });
  const sw = img.width, sh = img.height;
  const th = Math.round(sh * tw / sw);
  const out = Buffer.alloc(tw * th * 4);
  const sx = sw / tw, sy = sh / th;
  for (let y = 0; y < th; y++) {
    const y0 = Math.floor(y * sy), y1 = Math.min(sh, Math.max(y0 + 1, Math.floor((y + 1) * sy)));
    for (let x = 0; x < tw; x++) {
      const x0 = Math.floor(x * sx), x1 = Math.min(sw, Math.max(x0 + 1, Math.floor((x + 1) * sx)));
      let r = 0, g = 0, b = 0, n = 0;
      for (let yy = y0; yy < y1; yy++) {
        for (let xx = x0; xx < x1; xx++) {
          const i = (yy * sw + xx) * 4;
          r += img.data[i]; g += img.data[i + 1]; b += img.data[i + 2]; n++;
        }
      }
      const o = (y * tw + x) * 4;
      out[o] = r / n; out[o + 1] = g / n; out[o + 2] = b / n; out[o + 3] = 255;
    }
  }
  return jpeg.encode({ data: out, width: tw, height: th }, q).data;
}

const photos = fs.readdirSync(path.join(ROOT, 'assets')).filter(f => /^(pal2?|xh)-.*\.jpg$/.test(f));
let before = 0, after = 0;
photos.forEach(f => {
  const src = fs.readFileSync(path.join(ROOT, 'assets', f));
  const outBuf = resizeJpeg(src, PHOTO_W, PHOTO_Q);
  fs.writeFileSync(path.join(DIST, f), outBuf);
  before += src.length; after += outBuf.length;
});

console.log('dist 生成完成');
console.log('  照片 ' + photos.length + ' 张: ' + (before / 1024 / 1024).toFixed(2) + 'MB -> ' + (after / 1024 / 1024).toFixed(2) + 'MB (宽 ' + PHOTO_W + 'px, q' + PHOTO_Q + ')');
console.log('  index.html ' + (fs.statSync(path.join(DIST, 'index.html')).size / 1024).toFixed(0) + 'KB');
console.log('  app.js     ' + (fs.statSync(path.join(DIST, 'app.js')).size / 1024).toFixed(0) + 'KB');
