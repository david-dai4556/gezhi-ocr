const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="local-token"]').content;
let file = null, objectUrl = null, data = [], scores = [], merges = [], selected = null, busy = false;
function status(message, kind = '') { $('status').textContent = message; $('status').className = kind; }
function controls(value) {
  busy = value;
  for (const id of ['recognize', 'rotate']) $(id).disabled = value || !file;
  for (const id of ['export', 'addRow', 'addCol', 'deleteRow', 'deleteCol', 'unmerge', 'copy']) $(id).disabled = value || !data.length;
  $('replace').disabled = value; $('mode').disabled = value;
  $('grid').querySelectorAll('td').forEach(td => td.contentEditable = String(!value));
}
function acceptFile(value) {
  if (busy || !value) return;
  if (value.size > 24 * 1024 * 1024) return status('图片不能超过 24 MB。', 'error');
  if (value.type && !value.type.startsWith('image/')) return status('请选择图片文件。', 'error');
  file = value; data = []; scores = []; merges = []; selected = null;
  if (objectUrl) URL.revokeObjectURL(objectUrl);
  objectUrl = URL.createObjectURL(file);
  $('preview').src = objectUrl; $('preview').hidden = false; $('emptyImage').hidden = true;
  $('fileInfo').textContent = file.name || '粘贴的图片';
  $('emptyResult').hidden = false; $('resultArea').hidden = true; $('dimensions').textContent = '等待识别';
  controls(false); status('图片已就绪 · 点击“识别表格”');
}
$('preview').onerror = () => { file = null; controls(false); status('浏览器无法预览该图片，请转换为 PNG 或 JPG 后重试。', 'error'); };
$('file').onchange = event => { acceptFile(event.target.files[0]); event.target.value = ''; };
function pick() { if (!busy) $('file').click(); }
$('dropzone').onclick = pick; $('replace').onclick = pick;
$('dropzone').onkeydown = event => { if (['Enter', ' '].includes(event.key)) { event.preventDefault(); pick(); } };
for (const name of ['dragover', 'dragleave', 'drop']) $('dropzone').addEventListener(name, event => {
  event.preventDefault(); $('dropzone').classList.toggle('dragover', name === 'dragover');
  if (name === 'drop') acceptFile(event.dataTransfer.files[0]);
});
document.addEventListener('paste', event => {
  const picture = [...(event.clipboardData?.items || [])].find(x => x.type.startsWith('image/'));
  if (picture) { event.preventDefault(); acceptFile(picture.getAsFile()); }
});
$('rotate').onclick = async () => {
  controls(true);
  try {
    const bitmap = await createImageBitmap(file);
    if (bitmap.width * bitmap.height > 25000000) { bitmap.close(); throw Error('图片超过 2500 万像素，请缩小后再旋转。'); }
    const canvas = document.createElement('canvas'); canvas.width = bitmap.height; canvas.height = bitmap.width;
    const ctx = canvas.getContext('2d'); ctx.translate(canvas.width, 0); ctx.rotate(Math.PI / 2); ctx.drawImage(bitmap, 0, 0); bitmap.close();
    const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
    if (!blob) throw Error('图片旋转失败');
    controls(false); acceptFile(new File([blob], '旋转后的图片.png', {type: 'image/png'}));
  } catch (error) { status(error.message, 'error'); } finally { controls(false); }
};
async function api(path, options) {
  const response = await fetch(path, {...options, headers: {'X-Local-Token': token, ...options.headers}});
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw Error(detail.error || `请求失败（${response.status}）`);
  }
  return response;
}
$('recognize').onclick = async () => {
  controls(true); status('正在本地识别… 首次加载模型可能需要稍等。', 'busy');
  const body = new FormData(); body.append('image', file); body.append('mode', $('mode').value);
  try {
    const result = await (await api('/api/recognize', {method: 'POST', body})).json();
    data = result.data; scores = result.scores; merges = result.merges; selected = null;
    $('resultNote').textContent = result.note;
    render(); status(`识别完成 · ${result.method} · ${result.count} 段文字。请对照原图校对。`);
  } catch (error) { status(error.message, 'error'); } finally { controls(false); }
};
function column(n) { let value = ''; do { value = String.fromCharCode(65+n%26)+value; n = Math.floor(n/26)-1; } while (n>=0); return value; }
function render() {
  $('emptyResult').hidden = true; $('resultArea').hidden = false;
  $('dimensions').textContent = `${data.length} 行 × ${data[0].length} 列`;
  const grid = $('grid'); grid.replaceChildren();
  const head = grid.createTHead().insertRow(); head.append(document.createElement('th'));
  for (let c=0;c<data[0].length;c++) { const th=document.createElement('th'); th.textContent=column(c); head.append(th); }
  const body = grid.createTBody();
  const hidden = new Set(), origins = new Map();
  for (const m of merges) {
    origins.set(`${m[0]},${m[1]}`, m);
    for(let r=m[0];r<=m[2];r++) for(let c=m[1];c<=m[3];c++) if(r!==m[0]||c!==m[1]) hidden.add(`${r},${c}`);
  }
  data.forEach((row,r) => {
    const tr=body.insertRow(), th=document.createElement('th'); th.textContent=r+1; tr.append(th);
    row.forEach((value,c) => {
      if(hidden.has(`${r},${c}`)) return;
      const td=tr.insertCell(); td.textContent=value; td.contentEditable='true'; td.spellcheck=false;
      td.setAttribute('aria-label', `${column(c)}${r+1}`);
      if((scores[r]?.[c] ?? 1)<.85 && value) { td.className='low'; td.title='识别置信度较低，请核对原图'; }
      const m=origins.get(`${r},${c}`); if(m) { td.rowSpan=m[2]-r+1; td.colSpan=m[3]-c+1; }
      td.onfocus=()=>{selected=[r,c];};
      td.oninput=()=>{data[r][c]=td.innerText; td.classList.remove('low');};
      td.addEventListener('paste', event => {
        if ([...(event.clipboardData?.items || [])].some(x=>x.type.startsWith('image/'))) return;
        event.preventDefault(); const text=event.clipboardData.getData('text/plain');
        const sel=window.getSelection(); if(sel.rangeCount) {const range=sel.getRangeAt(0);range.deleteContents();const node=document.createTextNode(text);range.insertNode(node);range.setStartAfter(node);range.collapse(true);sel.removeAllRanges();sel.addRange(range);}
        data[r][c]=td.innerText; td.classList.remove('low');
      });
    });
  });
}
$('addRow').onclick = () => { if(data.length>=2000)return status('最多支持 2000 行','error'); data.push(Array(data[0].length).fill('')); render(); };
$('addCol').onclick = () => { if(data[0].length>=200)return status('最多支持 200 列','error'); data.forEach(row=>row.push('')); render(); };
function deleteAxis(axis) {
  if(!selected)return status('请先点击要删除的行或列中的一个单元格。','error');
  if(merges.length)return status('请先“取消合并”，再删除行或列。','error');
  if((axis===0?data.length:data[0].length)<=1)return status('至少保留一行和一列。','error');
  if(!confirm(`删除所选${axis===0?'行':'列'}及其内容？`))return;
  if(axis===0){data.splice(selected[0],1);scores.splice(selected[0],1);}else{data.forEach(row=>row.splice(selected[1],1));scores.forEach(row=>row.splice(selected[1],1));}
  selected=null;render();
}
$('deleteRow').onclick=()=>deleteAxis(0); $('deleteCol').onclick=()=>deleteAxis(1);
$('unmerge').onclick=()=>{merges=[];render();status('已取消合并，内容保留在原区域的左上角。');};
$('copy').onclick=async()=>{try{await navigator.clipboard.writeText(data.map(row=>row.map(v=>v.replace(/\t|\r?\n/g,' ')).join('\t')).join('\n'));status('已复制，可粘贴到 Excel。需要保留编号格式时请使用“下载 Excel”。');}catch{status('剪贴板不可用，请使用“下载 Excel”。','error');}};
$('export').onclick=async()=>{
  controls(true);
  try{
    const response=await api('/api/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({data,merges})});
    const url=URL.createObjectURL(await response.blob()), a=document.createElement('a'); a.href=url;
    a.download=((file?.name||'识别结果').replace(/\.[^.]+$/,'')||'识别结果')+'.xlsx';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);status('Excel 已生成，已交给浏览器下载。');
  }catch(error){status(error.message,'error');}finally{controls(false);}
};
