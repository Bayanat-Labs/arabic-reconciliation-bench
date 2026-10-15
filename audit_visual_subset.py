#!/usr/bin/env python3
"""Audit rendered image bytes, visible text, field geometry and paired pages.
SPDX-License-Identifier: Apache-2.0
"""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import re
import struct
import zlib
import pyarrow.parquet as pq


def cmap_points(path):
    """Read Unicode cmap formats 4/12 without a font-tool dependency."""
    b=path.read_bytes();tables=struct.unpack_from('>H',b,4)[0];points=set()
    for i in range(tables):
        tag,_,offset,_=struct.unpack_from('>4sIII',b,12+16*i)
        if tag!=b'cmap':continue
        _,n=struct.unpack_from('>HH',b,offset)
        for j in range(n):
            platform,encoding,sub=struct.unpack_from('>HHI',b,offset+4+8*j)
            if platform not in (0,3):continue
            p=offset+sub;kind=struct.unpack_from('>H',b,p)[0]
            if kind==12:
                groups=struct.unpack_from('>I',b,p+12)[0]
                for k in range(groups):
                    first,last,glyph=struct.unpack_from('>III',b,p+16+12*k)
                    points.update(range(first+(glyph==0),last+1))
            elif kind==4:
                count=struct.unpack_from('>H',b,p+6)[0]//2
                end=p+14;start=end+2*count+2;delta=start+2*count;rangeoff=delta+2*count
                for k in range(count):
                    hi=struct.unpack_from('>H',b,end+2*k)[0];lo=struct.unpack_from('>H',b,start+2*k)[0]
                    d=struct.unpack_from('>h',b,delta+2*k)[0];r=struct.unpack_from('>H',b,rangeoff+2*k)[0]
                    for code in range(lo,hi+1):
                        if code==65535:continue
                        if r:
                            glyph=struct.unpack_from('>H',b,rangeoff+2*k+r+2*(code-lo))[0]
                            if glyph:glyph=(glyph+d)&65535
                        else:glyph=(code+d)&65535
                        if glyph:points.add(code)
    return points


def png_dimensions(data):
    if data[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError('Not PNG')
    p=8;idat=[];size=None;ended=False
    while p<len(data):
        length=struct.unpack_from('>I',data,p)[0];kind=data[p+4:p+8];payload=data[p+8:p+8+length]
        crc=struct.unpack_from('>I',data,p+8+length)[0]
        if zlib.crc32(kind+payload)&0xffffffff!=crc:raise ValueError('PNG CRC mismatch')
        if kind==b'IHDR':size=struct.unpack_from('>II',payload,0)
        elif kind==b'IDAT':idat.append(payload)
        elif kind==b'IEND':ended=True
        p+=12+length
    if not ended or p!=len(data) or not zlib.decompress(b''.join(idat)):raise ValueError('Invalid PNG payload')
    return size


def audit(release):
    output=release/'visual_subset';manifest=json.loads((output/'render_manifest.json').read_text())
    errors=Counter();samples={};counts=Counter();wanted={p['case_id'] for p in manifest['packets']};cases={}
    def require(condition,check,example=None):
        if not condition:
            errors[check]+=1
            if len(samples.setdefault(check,[]))<4:samples[check].append(example)
    for split in ('test','challenge'):
        for path in sorted((release/'data'/'cases').glob(split+'-*.parquet')):
            for batch in pq.ParquetFile(path).iter_batches(batch_size=64,columns=['case_id','family_id','question','documents']):
                for row in batch.to_pylist():
                    if row['case_id'] in wanted:cases[row['case_id']]=row
    require(set(cases)==wanted,'source_case_coverage')
    expected_pages={};paired=defaultdict(dict);all_text=''
    for packet in manifest['packets']:
        c=cases[packet['case_id']];docs={d['doc_id']:d for d in c['documents']}
        directory=output/'packets'/packet['case_id']
        visible=json.loads((directory/'visible_text.json').read_text())
        require(visible=={'case_id':c['case_id'],'question':c['question'],'documents':c['documents']},'packet_visible_text',c['case_id'])
        pdf=(output/packet['packet_pdf']).read_bytes()
        require(hashlib.sha256(pdf).hexdigest()==packet['pdf_sha256'],'pdf_checksum',c['case_id'])
        require(pdf.startswith(b'%PDF-'),'pdf_magic',c['case_id'])
        require(len(docs)==len(packet['pages']),'packet_document_count',c['case_id'])
        for number,page in enumerate(packet['pages'],1):
            require(page.get('literal_order_checked') is True,'literal_source_order_check',packet['case_id'])
            counts['literal_tokens_position_checked']+=page.get('bidi_tokens_checked',0)
            expected_pages[page['page_id']]=(packet,page,docs[page['doc_id']],number)
        paired[(packet['family_id'],packet['view'])][packet['world']]={p['doc_id']:p['image_sha256'] for p in packet['pages']}
    observed=set();chars=set()
    for path in sorted((release/'data'/'pages').glob('*.parquet')):
        split=path.name.split('-',1)[0]
        schema=pq.ParquetFile(path).schema_arrow
        feature=json.loads(schema.metadata[b'huggingface'])['info']['features']['image']
        require(feature.get('_type')=='Image','hf_image_feature',path.name)
        for batch in pq.ParquetFile(path).iter_batches(batch_size=20):
            for row in batch.to_pylist():
                counts['pages']+=1;counts['split.'+split]+=1
                require(row['page_id'] not in observed,'duplicate_page_id',row['page_id']);observed.add(row['page_id'])
                packet,page,doc,number=expected_pages[row['page_id']]
                require(row['case_id']==packet['case_id'] and row['doc_id']==doc['doc_id'] and row['family_id']==packet['family_id'] and row['page_no']==number,'page_associations',row['page_id'])
                require(split==packet['split'],'page_split',row['page_id'])
                require(row['text']==doc['text'] and row['title']==doc['title'] and row['question']==cases[row['case_id']]['question'],'page_visible_text',row['page_id'])
                image=row['image'];require(image['path'] is None and bool(image['bytes']),'embedded_image',row['page_id'])
                require(hashlib.sha256(image['bytes']).hexdigest()==page['image_sha256'],'png_checksum',row['page_id'])
                require(png_dimensions(image['bytes'])==(794,1123),'png_dimensions',row['page_id'])
                require((release/row['pdf_path']).is_file(),'pdf_reference',row['page_id'])
                boxes=json.loads(row['field_boxes_json']);expected=dict(re.findall(r'^\[([^\]]+)\]\s*(.*)$',doc['text'],re.M))
                require({f['field_id'] for f in boxes['fields']}==set(expected),'field_id_coverage',row['page_id'])
                for field in boxes['fields']:
                    counts['fields']+=1;x0,y0,x1,y1=field['bbox_pixels_xyxy']
                    require(0<=x0<x1<=794 and 0<=y0<y1<=1123,'field_box_bounds',[row['page_id'],field['field_id']])
                    text=' '.join(field['visible_text'].split());target=' '.join(('['+field['field_id']+'] '+expected[field['field_id']]).split())
                    require(text==target,'field_text_equality',[row['page_id'],field['field_id']])
                chars.update(ord(c) for c in doc['text']+doc['title'] if not c.isspace())
    require(observed==set(expected_pages),'page_manifest_coverage')
    for (family,view),worlds in paired.items():
        if 'clean' not in worlds or 'critical_edit' not in worlds:require(False,'complete_world_pair',[family,view]);continue
        before,after=worlds['clean'],worlds['critical_edit']
        require(set(before)==set(after),'critical_document_sets',[family,view])
        require(sum(before[k]!=after.get(k) for k in before)==1,'critical_single_changed_page',[family,view])
    available=set()
    for path in (output/'fonts').glob('*.ttf'):available.update(cmap_points(path))
    absent=sorted(chars-available)
    require(not absent,'font_character_coverage',[f'U+{c:04X}' for c in absent])
    require(counts['pages']==manifest['page_count'],'total_pages')
    require(counts['fields']==manifest['field_count'],'total_fields')
    return {'status':'passed' if not errors else 'failed','counts':dict(counts),'packets':len(wanted),'families':manifest['family_count'],
            'critical_pairs_checked':len(paired),'unsupported_source_characters':[f'U+{c:04X}' for c in absent],
            'failed_checks':dict(errors),'failure_examples':samples,
            'scope':'Every page PNG CRC/decompression/hash/dimensions, exact visible source text, field marker/text coverage and bounds, source/split links, full source-character font coverage, PDF hashes, per-token character-position checks for literal source order, and exactly one changed document image per clean-to-critical pair. This is structural/render QA, not expert semantic validation.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--release-dir',type=Path,required=True);args=parser.parse_args()
    report=audit(args.release_dir);(args.release_dir/'visual_subset'/'validation_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2));raise SystemExit(0 if report['status']=='passed' else 1)
