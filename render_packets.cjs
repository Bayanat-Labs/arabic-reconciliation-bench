#!/usr/bin/env node
/** Isolated Chromium renderer for already-visible synthetic packet text.
 * SPDX-License-Identifier: Apache-2.0
 * No gold labels, canonical values, mechanisms or world names enter page HTML.
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const readline = require('readline');

function args(argv) {
  const result={};
  for(let i=0;i<argv.length;i+=2) {
    if(!argv[i].startsWith('--') || argv[i+1]===undefined) throw Error('Expected --option value arguments');
    result[argv[i].slice(2)]=argv[i+1];
  }
  for(const key of ['jobs','output-dir','fonts-dir']) if(!result[key]) throw Error('Missing --'+key);
  return result;
}
const opt=args(process.argv.slice(2));
const {chromium}=require(opt['playwright-module'] || 'playwright');
const {PDFDocument}=require(opt['pdf-lib-module'] || 'pdf-lib');
const WIDTH=794,HEIGHT=1123;
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// Numeric dates and mixed-script identifiers must remain in source order in
// RTL paragraphs. Otherwise Unicode bidi can display YYYY-MM-DD as DD-MM-YYYY.
function bidiText(value) {
  const token=/[A-Za-z0-9\u0660-\u0669\u06f0-\u06f9][A-Za-z0-9\u0660-\u0669\u06f0-\u06f9.,\u066b\u066c:/%\u066a+_=\-]*/g;
  let output='',last=0;
  for(const match of String(value).matchAll(token)) {
    output+=esc(String(value).slice(last,match.index))+`<bdi dir="ltr" style="unicode-bidi:isolate-override">${esc(match[0])}</bdi>`;
    last=match.index+match[0].length;
  }
  return output+esc(String(value).slice(last));
}
const safeName=s=>{if(!/^[A-Za-z0-9._-]+$/.test(s))throw Error('Unsafe identifier filename');return s;};
const fontFiles=['NotoSansArabic-Regular.ttf','NotoSansArabic-Bold.ttf','NotoSans-Regular.ttf','NotoSans-Bold.ttf'];
let fontCss='';
const fontHashes={};
for(const file of fontFiles) {
  const data=fs.readFileSync(path.join(opt['fonts-dir'],file));fontHashes[file]=sha(data);
  const family=file.startsWith('NotoSansArabic')?'AtlasArabic':'AtlasLatin';
  fontCss+=`@font-face{font-family:${family};font-style:normal;font-weight:${file.includes('Bold')?700:400};src:url(data:font/ttf;base64,${data.toString('base64')}) format('truetype');font-display:block;}`;
}
fontCss+='.row-heading{font-size:10px;line-height:1.5;font-weight:700;color:#60798b;margin:8px 3px 4px;white-space:pre-wrap}';

function segments(doc) {
  const expected=doc.expected_fields || [];
  const byId=new Map(expected.map(f=>[f.id,f])),seen=new Set(),groups=[];
  let pending=[],preamble='';
  for(const line of doc.text.split('\n')) {
    const match=line.match(/^\[([^\]]+)\]\s*(.*)$/);
    if(!match){pending.push(line);continue;}
    const field=byId.get(match[1]);
    if(!field || seen.has(field.id))throw Error('Unexpected/repeated field marker: '+match[1]);
    seen.add(field.id);
    if(!groups.length){preamble=pending.join('\n').trim();pending=[];}
    const row=field.row_id||'';
    if(!groups.length || groups[groups.length-1].id!==row || pending.length) {
      groups.push({id:row,heading:pending.join('\n').trim(),fields:[]});pending=[];
    }
    groups[groups.length-1].fields.push({id:field.id,row_id:row,text:match[2]});
  }
  if(seen.size!==expected.length || !seen.size)throw Error('Field set does not equal expected visible IDs: '+doc.doc_id);
  return {preamble,groups,trailer:pending.join('\n').trim()};
}

function article(doc,index,color) {
  const parsed=segments(doc),groups=parsed.groups;
  const fieldHtml=f=>`<div class="field" data-field-id="${esc(f.id)}"><div class="field-id" dir="ltr">[${esc(f.id)}]</div><div class="field-text">${bidiText(f.text)}</div></div>`;
  return `<article class="doc-page" data-doc-id="${esc(doc.doc_id)}" style="--accent:${color};--body-size:15px"><div class="page-header"><div><div class="eyebrow">بيانات اصطناعية · SYNTHETIC BENCHMARK</div><h1>${esc(doc.title)}</h1></div><div class="doc-id" dir="ltr">${esc(doc.doc_id)}</div></div><div class="content">${parsed.preamble?`<div class="preamble">${bidiText(parsed.preamble)}</div>`:''}${groups.map(g=>`${g.heading?`<div class="row-heading">${bidiText(g.heading)}</div>`:''}<section class="field-grid ${g.id?'line-grid':''} ${g.fields.some(f=>f.text.length>170)?'wide-grid':''}">${g.fields.map(fieldHtml).join('')}</section>`).join('')}${parsed.trailer?`<div class="preamble">${bidiText(parsed.trailer)}</div>`:''}</div><footer><span>مستند اصطناعي للتقييم. لا يمثل معاملة حقيقية أو متطلبات قانونية أو ضريبية.</span><span dir="ltr">${index+1}</span></footer></article>`;
}

function html(job) {
  const colors=['#107d7a','#294c84','#725076','#6b642d'];
  const color=colors[parseInt(sha(Buffer.from(job.family_id)).slice(0,4),16)%colors.length];
  return `<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>Synthetic procurement evidence</title><style>${fontCss}
  @page{size:${WIDTH}px ${HEIGHT}px;margin:0}*{box-sizing:border-box}html,body{margin:0;padding:0;background:#fff;color:#173146}body{font-family:AtlasArabic,AtlasLatin,sans-serif}.doc-page{width:${WIDTH}px;height:${HEIGHT}px;padding:34px 38px 48px;position:relative;break-after:page;overflow:hidden;background:#fff}.doc-page:last-child{break-after:auto}.page-header{height:104px;display:flex;justify-content:space-between;gap:16px;border-bottom:4px solid var(--accent);margin-bottom:18px}.eyebrow{font:700 11px AtlasArabic,AtlasLatin,sans-serif;color:var(--accent);letter-spacing:.1px}h1{font-size:27px;line-height:1.6;margin:5px 0 0;max-width:600px}.doc-id{font:700 14px AtlasLatin,AtlasArabic,sans-serif;color:#526a7b;padding-top:34px;min-width:40px}.content{font-size:var(--body-size);line-height:1.65}.preamble{font-size:var(--body-size);white-space:pre-wrap;margin-bottom:12px}.field-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px;margin:0 0 12px;padding:10px;border:1px solid #d7e2e9;border-radius:7px;break-inside:avoid}.line-grid{grid-template-columns:repeat(3,minmax(0,1fr));background:#f5f9fb;border-right:3px solid var(--accent)}.wide-grid{grid-template-columns:1fr}.field{min-width:0;padding:3px 6px 5px;border-bottom:1px solid #edf1f4;break-inside:avoid}.field-id{color:#678091;font:400 8px AtlasLatin,AtlasArabic,sans-serif;line-height:1.4;text-align:right}.field-text{white-space:pre-wrap;overflow-wrap:anywhere;unicode-bidi:plaintext;direction:rtl}footer{position:absolute;bottom:20px;right:38px;left:38px;border-top:1px solid #d7e2e9;padding-top:9px;display:flex;justify-content:space-between;gap:12px;font-size:9px;color:#5c7384;line-height:1.6}
  </style></head><body>${job.documents.map((d,i)=>article(d,i,color)).join('')}</body></html>`;
}

async function render(browser,job) {
  const caseId=safeName(job.case_id),dir=path.join(opt['output-dir'],'packets',caseId);
  fs.mkdirSync(dir,{recursive:true});
  const page=await browser.newPage({viewport:{width:WIDTH,height:HEIGHT},deviceScaleFactor:1});
  await page.route(/^https?:\/\//,route=>route.abort());
  try {
    await page.setContent(html(job),{waitUntil:'load'});
    await page.evaluate(()=>document.fonts.ready);
    const layout=await page.evaluate(()=>{
      const results=[];
      for(const article of document.querySelectorAll('.doc-page')) {
        const content=article.querySelector('.content'),footer=article.querySelector('footer');
        let size=15;
        for(const candidate of [15,14,13,12,11.5,11]) {
          size=candidate;article.style.setProperty('--body-size',candidate+'px');
          if(content.getBoundingClientRect().bottom<=footer.getBoundingClientRect().top-12)break;
        }
        const a=article.getBoundingClientRect(),bottom=content.getBoundingClientRect().bottom;
        if(bottom>footer.getBoundingClientRect().top-12)throw Error('One-page content overflow: '+article.dataset.docId);
        let bidiTokens=0;
        for(const token of article.querySelectorAll('bdi')) {
          const text=token.firstChild;
          if(!text || text.nodeType!==Node.TEXT_NODE)continue;
          let previous=null;
          for(let i=0;i<text.length;i++) {
            const range=document.createRange();range.setStart(text,i);range.setEnd(text,i+1);
            const box=range.getBoundingClientRect();
            if(previous && Math.abs(box.top-previous.top)<1 && box.left<previous.left-.5)
              throw Error('Literal token visually reverses source order: '+text.textContent);
            previous=box;
          }
          bidiTokens++;
        }
        const fields=[...article.querySelectorAll('[data-field-id]')].map(n=>{
          const r=n.getBoundingClientRect(),t=n.querySelector('.field-text');
          if(r.left<a.left || r.right>a.right || r.top<a.top || r.bottom>a.bottom)throw Error('Field box escapes page');
          if(t.scrollWidth>t.clientWidth+1)throw Error('Text horizontally clipped: '+n.dataset.fieldId);
          return {field_id:n.dataset.fieldId,visible_text:n.innerText,
            bbox_css_xywh:[r.left-a.left,r.top-a.top,r.width,r.height],
            bbox_pixels_xyxy:[Math.floor(r.left-a.left),Math.floor(r.top-a.top),Math.ceil(r.right-a.left),Math.ceil(r.bottom-a.top)]};
        });
        results.push({doc_id:article.dataset.docId,width:a.width,height:a.height,body_font_pixels:size,bidi_tokens_checked:bidiTokens,literal_order_checked:true,fields});
      }
      return results;
    });
    const pdfOriginal=await page.pdf({printBackground:true,preferCSSPageSize:true,tagged:false});
    const pdf=await PDFDocument.load(pdfOriginal,{updateMetadata:false});
    if(pdf.getPageCount()!==job.documents.length)throw Error('PDF pagination differs from document count');
    pdf.setTitle('Synthetic Arabic procurement evidence');pdf.setAuthor('Bayanat Labs');
    pdf.setSubject('Original controlled synthetic benchmark documents');
    pdf.setCreator('Arabic Reconciliation Bench isolated Chromium renderer');
    pdf.setCreationDate(new Date('2026-10-15T00:00:00Z'));pdf.setModificationDate(new Date('2026-10-15T00:00:00Z'));
    const pdfBytes=Buffer.from(await pdf.save({useObjectStreams:true}));
    fs.writeFileSync(path.join(dir,'packet.pdf'),pdfBytes);
    const pages=[];
    for(let i=0;i<layout.length;i++) {
      const record=layout[i],docId=safeName(record.doc_id),pngName=docId+'.png';
      const png=await page.locator('.doc-page').nth(i).screenshot({animations:'disabled'});
      fs.writeFileSync(path.join(dir,pngName),png);
      const pdfPage=pdf.getPage(i),pdfSize=pdfPage.getSize();
      for(const f of record.fields) {
        const [x,y,w,h]=f.bbox_css_xywh;
        f.bbox_pdf_points_xywh=[x*pdfSize.width/record.width,(record.height-y-h)*pdfSize.height/record.height,w*pdfSize.width/record.width,h*pdfSize.height/record.height];
      }
      pages.push({...record,page_index:i,image:pngName,image_sha256:sha(png),image_bytes:png.length,pdf_points:[pdfSize.width,pdfSize.height]});
    }
    const visible={case_id:job.case_id,question:job.question,documents:job.documents.map(d=>({doc_id:d.doc_id,title:d.title,text:d.text}))};
    fs.writeFileSync(path.join(dir,'visible_text.json'),JSON.stringify(visible,null,2)+'\n');
    const boxes={case_id:job.case_id,box_semantics:'Exact DOM field containers at 1 CSS pixel per PNG pixel; not glyph polygons or human annotations. PDF boxes are scaled page-coordinate counterparts.',pages};
    fs.writeFileSync(path.join(dir,'field_boxes.json'),JSON.stringify(boxes,null,2)+'\n');
    if(opt['keep-html']==='true')fs.writeFileSync(path.join(dir,'packet.html'),html(job));
    return {case_id:job.case_id,family_id:job.family_id,split:job.split,mechanism:job.mechanism,world:job.world,view:job.view,
      packet_pdf:'packets/'+caseId+'/packet.pdf',pdf_sha256:sha(pdfBytes),pdf_bytes:pdfBytes.length,
      visible_text:'packets/'+caseId+'/visible_text.json',field_boxes:'packets/'+caseId+'/field_boxes.json',
      pages:pages.map(p=>({doc_id:p.doc_id,image:'packets/'+caseId+'/'+p.image,image_sha256:p.image_sha256,image_bytes:p.image_bytes,fields:p.fields.length,body_font_pixels:p.body_font_pixels,bidi_tokens_checked:p.bidi_tokens_checked,literal_order_checked:p.literal_order_checked}))};
  } finally {await page.close();}
}

(async()=>{
  fs.mkdirSync(opt['output-dir'],{recursive:true});
  const browser=await chromium.launch({headless:true,executablePath:opt['chrome-executable']||undefined});
  const manifest={renderer:'isolated headless Chromium via Playwright',chromium:await browser.version(),node:process.version,
    page_css_pixels:[WIDTH,HEIGHT],device_scale_factor:1,font_sha256:fontHashes,packets:[]};
  try {
    const lines=readline.createInterface({input:fs.createReadStream(opt.jobs),crlfDelay:Infinity});
    for await(const line of lines) {
      if(!line.trim())continue;
      const record=await render(browser,JSON.parse(line));manifest.packets.push(record);
      fs.writeFileSync(path.join(opt['output-dir'],'render_manifest.json'),JSON.stringify(manifest,null,2)+'\n');
      console.log(JSON.stringify({rendered_packets:manifest.packets.length,case_id:record.case_id,pages:record.pages.length}));
    }
    manifest.packet_count=manifest.packets.length;manifest.page_count=manifest.packets.reduce((n,p)=>n+p.pages.length,0);
    manifest.family_count=new Set(manifest.packets.map(p=>p.family_id)).size;
    manifest.field_count=manifest.packets.reduce((n,p)=>n+p.pages.reduce((m,d)=>m+d.fields,0),0);
    manifest.complete=true;
    fs.writeFileSync(path.join(opt['output-dir'],'render_manifest.json'),JSON.stringify(manifest,null,2)+'\n');
    console.log(JSON.stringify({complete:true,packets:manifest.packet_count,pages:manifest.page_count,families:manifest.family_count}));
  } finally {await browser.close();}
})().catch(e=>{console.error(e.stack||String(e));process.exitCode=1;});
