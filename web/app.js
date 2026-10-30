'use strict';
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const app = {apiBase:localStorage.getItem('mada-api-base')||'', token:sessionStorage.getItem('mada-api-token')||'', tab:'home', current:null, format:'mp4', jobs:[], health:null, filter:'all', busy:false};
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmtDuration = seconds => {if (!Number.isFinite(Number(seconds)) || seconds === null) return 'مدة غير معروفة'; let t = Math.round(Number(seconds)); const h = Math.floor(t/3600), m = Math.floor((t%3600)/60), s = t%60; return (h?h+':':'')+String(m).padStart(h?2:1,'0')+':'+String(s).padStart(2,'0');};
const fmtBytes = (size) => {if (size == null || !Number.isFinite(Number(size))) return '—'; const n=Number(size); if(n<1024)return `${n} B`; const i=Math.min(Math.floor(Math.log(n)/Math.log(1024)),4); return `${(n/1024**i).toFixed(1)} ${['B','KB','MB','GB','TB'][i]}`;};
const isUrl = value => /^(https?:\/\/|www\.)/i.test(value.trim());
const getError = (error) => error.message || 'تعذر إكمال العملية';
function toast(message,error=false){ const el=document.createElement('div');el.className='toast'+(error?' error':'');el.textContent=message;$('#toastArea').append(el);setTimeout(()=>el.remove(),5200); }
function apiUrl(url){return (app.apiBase || '') + url;}
async function api(url, data=null, method='POST'){
  const opts={method,headers:{'Accept':'application/json'}};
  if(app.token)opts.headers['Authorization']='Bearer '+app.token;
  if(data!==null){opts.headers['Content-Type']='application/json';opts.body=JSON.stringify(data);}
  let res;
  try{res=await fetch(apiUrl(url),opts);}catch(e){throw new Error('تعذر الاتصال بمحرك التنزيل. افتح الإعدادات للتحقق من عنوان الخادم والاتصال.');}
  let payload; try{payload=await res.json();}catch{throw new Error('استجابة غير متوقعة من المحرك.');}
  if(!res.ok)throw new Error(payload.error || 'فشلت العملية.');
  return payload;
}
function switchTab(next){app.tab=next;$$('.tab-panel').forEach(p=>p.classList.add('hidden'));$('#'+next+'Panel').classList.remove('hidden');$$('[data-tab]').forEach(b=>b.classList.toggle('active',b.dataset.tab===next));$('#pageTitle').innerHTML=({home:'أهلًا بك في MADA <span class="wave">✦</span>',downloads:'مكتبة التنزيلات <span class="wave">⇩</span>',settings:'الإعدادات <span class="wave">⚙</span>'})[next];window.scrollTo({top:0,behavior:'smooth'});if(next==='downloads')refreshJobs();if(next==='settings')checkHealth();}
function toggleTheme(){const val=document.body.classList.toggle('light')?'light':'dark';localStorage.setItem('mada-theme',val);}
function setLookupBusy(value){app.busy=value;$('#lookupBtn').disabled=value;$('#lookupBtnText').textContent=value?'جارٍ الاستعراض...':'استعراض';$('#lookupBtnIcon').textContent=value?'◌':'↗';}
async function lookup(value){
  if(!value){toast('ألصق رابط فيديو أو اكتب عبارة للبحث.',true);$('#urlInput').focus();return;}
  if(app.busy)return;
  setLookupBusy(true);$('#resultSection').classList.remove('hidden');$('#results').innerHTML='<div class="empty-state"><div class="empty-symbol">◌</div><h4>جارٍ التحليل...</h4><p>يتم الاتصال بمصدر المحتوى والتحقق من الملفات المتاحة.</p></div>';
  const asUrl=isUrl(value);
  $('#resultEyebrow').textContent=asUrl?'تفاصيل الفيديو':'نتائج البحث';
  $('#resultHeading').textContent=asUrl?'وجدنا الرابط':'البحث عن: '+value.slice(0,60);
  try{
    if(asUrl){const data=await api('/api/info',{url:value});const item=data.item;if(!item.url)item.url=value;renderVideo(item);}
    else{const data=await api('/api/search',{query:value});renderSearch(data.items||[]);}
  }catch(e){$('#results').innerHTML=`<div class="empty-state"><div class="empty-symbol">!</div><h4>لم نستطع استعراض المحتوى</h4><p>${esc(getError(e))}</p></div>`;toast(getError(e),true);}
  finally{setLookupBusy(false);}
}
function imageHtml(src, alt='صورة الفيديو'){return src&&/^https?:\/\//.test(src)?`<img src="${esc(src)}" alt="${esc(alt)}" loading="lazy" referrerpolicy="no-referrer" onerror="this.style.opacity='.25'">`:`<span style="font-size:36px;color:var(--accent)">▶</span>`;}
function renderVideo(item){app.current=item;$('#results').innerHTML=`<div class="result-video">${imageHtml(item.thumbnail)}<div class="result-main"><h4>${esc(item.title)}</h4><p>${esc(item.uploader||item.site||'فيديو')} • ${esc(fmtDuration(item.duration))}</p><p>${item.heights?.length?'الدقات المكتشفة: '+esc(item.heights.slice(0,6).join('p · '))+'p':'الجودات المتاحة حسب المصدر'}</p><button class="primary-btn" id="singleDownload" type="button">↓ اختيار التنزيل</button></div></div>`;$('#singleDownload').addEventListener('click',()=>openDialog(item));}
function renderSearch(items){app.searchResults=items;if(!items.length){$('#results').innerHTML='<div class="empty-state"><div class="empty-symbol">⌕</div><h4>لا توجد نتائج</h4><p>جرب اسمًا آخر، أو الصق رابط المقطع مباشرة.</p></div>';return;}$('#results').innerHTML='<p style="font-size:11px;color:var(--muted);margin:0 0 13px">نتائج البحث تُستخرج من YouTube. يمكنك لصق رابط أي موقع آخر يدعمه المحرك.</p><div class="search-grid">'+items.map((v,i)=>`<div class="search-card">${imageHtml(v.thumbnail)}<div class="result-main"><h4>${esc(v.title)}</h4><p>${esc(v.uploader||'YouTube')} • ${esc(fmtDuration(v.duration))}</p><button class="small-action" type="button" data-preview="${i}">استعراض وتنزيل ↗</button></div></div>`).join('')+'</div>';$$('[data-preview]').forEach(btn=>btn.addEventListener('click',async()=>{const item=items[+btn.dataset.preview];if(!item)return;const old=btn.textContent;btn.disabled=true;btn.textContent='جارٍ التحليل...';try{const response=await api('/api/info',{url:item.url});openDialog({...response.item,url:item.url});}catch(e){toast(getError(e),true);}finally{btn.disabled=false;btn.textContent=old;}}));}
function openDialog(item){app.current=item;app.format='mp4';$('#dialogTitle').textContent=item.title||'محتوى بدون عنوان';$('#dialogSub').textContent=[item.uploader,item.duration==null?'':fmtDuration(item.duration)].filter(Boolean).join(' • ')||item.site||'';const image=$('#dialogThumb');image.src=item.thumbnail||'';image.style.opacity=item.thumbnail?'1':'0.2';$$('.format-pill').forEach(b=>b.classList.toggle('selected',b.dataset.format==='mp4'));$('#qualityWrapper').classList.remove('hidden');$('#downloadDialog').classList.remove('hidden');document.body.style.overflow='hidden';}
function closeDialog(){$('#downloadDialog').classList.add('hidden');document.body.style.overflow='';}
async function download(){if(!app.current)return;const btn=$('#confirmDownload');btn.disabled=true;btn.textContent='جارٍ الإضافة...';try{const item=await api('/api/jobs',{url:app.current.url,format:app.format,quality:$('#qualitySelect').value});toast('أُضيف التنزيل إلى القائمة.');closeDialog();switchTab('downloads');}catch(e){toast(getError(e),true);}finally{btn.disabled=false;btn.textContent='↓ بدء التنزيل';}}
const statusText={queued:'في الانتظار',downloading:'جارٍ التنزيل',processing:'جارٍ تجهيز الملف',completed:'مكتمل',error:'فشل التنزيل',canceled:'أُلغي التنزيل',interrupted:'متوقف — أعد المحاولة'};
const active = j => ['queued','downloading','processing'].includes(j.status);
function renderJobs(){const jobs=app.jobs;$('#downloadCount').textContent=jobs.length;$('#statDone').textContent=jobs.filter(j=>j.status==='completed').length;$('#statActive').textContent=jobs.filter(active).length;$('#statAll').textContent=jobs.length;const filtered=jobs.filter(j=>app.filter==='all'||(app.filter==='active'?active(j):j.status==='completed'));if(!filtered.length){$('#jobsList').innerHTML='<div class="empty-state"><div class="empty-symbol">⇩</div><h4>لا توجد تنزيلات هنا بعد</h4><p>ابدأ من الرئيسية، وأضف رابط الفيديو الأول إلى قائمتك.</p></div>';return;}$('#jobsList').innerHTML=filtered.map(j=>{let sub=`${esc((j.format||'').toUpperCase())} • ${esc(statusText[j.status]||j.status)}`;if(j.status==='downloading')sub+=` • ${esc(Math.round(j.progress||0))}% • ${fmtBytes(j.downloaded)} / ${fmtBytes(j.total)}${j.speed?' • '+fmtBytes(j.speed)+'/s':''}${j.eta?' • '+Math.ceil(j.eta)+' ث':''}`;if(j.status==='completed')sub+=` • ${fmtBytes(j.total)}`;if(j.error)sub+=` • ${esc(j.error).slice(0,260)}`;return `<div class="job"><div class="job-thumb">${imageHtml(j.thumbnail||'')}</div><div class="job-details"><div class="job-title" title="${esc(j.title)}">${esc(j.title||'فيديو')}</div><div class="job-sub">${sub}</div>${active(j)?`<div class="job-progress"><div style="width:${Math.max(0,Math.min(100,Number(j.progress)||0))}%"></div></div>`:''}</div><div class="job-actions">${j.status==='completed'?`<button class="job-action play" data-action="play" data-id="${esc(j.id)}">▶ تشغيل</button><button class="job-action" data-action="save" data-id="${esc(j.id)}">↓ حفظ على الجهاز</button>`:''}${active(j)?`<button class="job-action danger" data-action="cancel" data-id="${esc(j.id)}">إلغاء</button>`:''}${['error','canceled','interrupted'].includes(j.status)?`<button class="job-action play" data-action="retry" data-id="${esc(j.id)}">↻ إعادة</button>`:''}${!active(j)?`<button class="job-action danger" data-action="delete" data-id="${esc(j.id)}">حذف</button>`:''}</div></div>`;}).join('');}
async function refreshJobs(){try{const resp=await api('/api/jobs',null,'GET');app.jobs=resp.jobs||[];renderJobs();$('#serverDot').classList.add('ready');$('#serverLabel').textContent='المحرك متصل';}catch(e){$('#serverDot').classList.remove('ready');$('#serverLabel').textContent='المحرك غير متصل';}}
async function checkHealth(){try{app.health=await api('/api/health',null,'GET');$('#serverDot').classList.add('ready');$('#serverLabel').textContent=app.health.engine?'جاهز لاستقبال الروابط':'يتطلب تثبيت yt-dlp';$('#engineStatus').textContent=app.health.engine?'✓ محرك yt-dlp مثبت ويعمل.':'✕ yt-dlp غير مثبت. شغّل ملف التثبيت.';$('#ffmpegStatus').textContent=app.health.ffmpeg?'✓ FFmpeg متاح لتحويل MP3 ودمج HD.':'⚠ FFmpeg غير مثبت؛ قد تتعطل بعض الصيغ والجودات.';$('#downloadDir').textContent=app.health.downloads_dir;}catch(e){$('#serverDot').classList.remove('ready');$('#serverLabel').textContent='المحرك غير متصل';$('#engineStatus').textContent='المحرك غير متصل';}}
async function handleJobAction(event){const btn=event.target.closest('[data-action][data-id]');if(!btn)return;const id=btn.dataset.id,action=btn.dataset.action;const j=app.jobs.find(v=>v.id===id);if(!j)return;btn.disabled=true;try{if(action==='play'||action==='save'){
      const windowRef=action==='play'?window.open('about:blank','_blank'):null;
      try{
        const ticket=await api(`/api/jobs/${id}/ticket`,{});
        const url=new URL(ticket.url, app.apiBase || location.origin);
        if(action==='save')url.searchParams.set('download','1');
        if(windowRef){windowRef.location.href=url.href;}
        else{const a=document.createElement('a');a.href=url.href;a.rel='noopener';a.download=j.filename||'media';document.body.append(a);a.click();a.remove();}
      }catch(e){if(windowRef)windowRef.close();throw e;}
      return;
    }else if(action==='retry'){await api('/api/jobs',{url:j.url,format:j.format,quality:j.quality});toast('أُعيدت إضافة الملف للتنزيل.');}else if(action==='delete'){if(!confirm('حذف هذا التنزيل وملفه من الجهاز؟')){btn.disabled=false;return;}await api(`/api/jobs/${id}/delete`,{});toast('حُذف التنزيل من السجل والجهاز.');}else{await api(`/api/jobs/${id}/cancel`,{});toast('طُلب إلغاء التنزيل.');}await refreshJobs();}catch(e){toast(getError(e),true);btn.disabled=false;}}
function saveConnection(){
  const raw=$('#apiBaseInput').value.trim().replace(/\/+$/,'');
  if(raw && !/^https:\/\//i.test(raw) && !/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/i.test(raw)){
    toast('اتصال الخادم البعيد يجب أن يكون HTTPS. يُسمح بـ HTTP المحلي فقط.',true);return;
  }
  if(raw && !/^https?:\/\/[^/]+$/i.test(raw)){toast('عنوان المحرك غير صحيح.',true);return;}
  app.apiBase=raw;app.token=$('#apiTokenInput').value.trim();
  localStorage.setItem('mada-api-base',raw);sessionStorage.setItem('mada-api-token',app.token);
  app.jobs=[];renderJobs();checkHealth();toast('حُفظت الإعدادات. جارٍ فحص الاتصال.');
}
function setup(){
  $('#apiBaseInput').value=app.apiBase;
  $('#apiTokenInput').value=app.token;
  $('#saveConnectionBtn').addEventListener('click',saveConnection);
  if(localStorage.getItem('mada-theme')==='light')document.body.classList.add('light');
  $$('[data-tab]').forEach(btn=>btn.addEventListener('click',()=>switchTab(btn.dataset.tab)));
  $('#themeBtn').addEventListener('click',toggleTheme);$('#settingsThemeBtn').addEventListener('click',toggleTheme);
  $('#lookupForm').addEventListener('submit',e=>{e.preventDefault();lookup($('#urlInput').value.trim());});
  $('#pasteBtn').addEventListener('click',async()=>{try{const text=await navigator.clipboard.readText();$('#urlInput').value=text;toast('تم لصق الرابط.');}catch{toast('الصق الرابط يدويًا باستخدام Ctrl+V.',true);$('#urlInput').focus();}});
  $('#clearResults').addEventListener('click',()=>$('#resultSection').classList.add('hidden'));
  $('#closeDialog').addEventListener('click',closeDialog);$('#downloadDialog').addEventListener('click',e=>{if(e.target===$('#downloadDialog'))closeDialog();});
  document.addEventListener('keydown',e=>{if(e.key==='Escape')closeDialog();});
  $$('.format-pill').forEach(btn=>btn.addEventListener('click',()=>{app.format=btn.dataset.format;$$('.format-pill').forEach(el=>el.classList.toggle('selected',el===btn));$('#qualityWrapper').classList.toggle('hidden',app.format!=='mp4');$('#dialogNotice').textContent=app.format==='mp3'?'يتطلب استخراج MP3 وجود FFmpeg على جهازك.':'يمكنك متابعة التنزيل في تبويب «التنزيلات».';}));
  $('#confirmDownload').addEventListener('click',download);
  $('#refreshBtn').addEventListener('click',refreshJobs);
  $$('.filter').forEach(btn=>btn.addEventListener('click',()=>{app.filter=btn.dataset.filter;$$('.filter').forEach(b=>b.classList.toggle('active',b===btn));renderJobs();}));
  $('#jobsList').addEventListener('click',handleJobAction);
  checkHealth();refreshJobs();setInterval(()=>{if(app.tab==='downloads'||app.jobs.some(active))refreshJobs();},1800);
  if('serviceWorker' in navigator)navigator.serviceWorker.register('./sw.js').catch(()=>{});
}
setup();
