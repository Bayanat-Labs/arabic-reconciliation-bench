#!/usr/bin/env python3
"""Select bounded complete families and render their already-visible packets.

The visual resource repeats controlled cases from the text dataset. It is not a
collection of additional independent transactions or real customer documents.
Requires pyarrow, Node, Playwright, pdf-lib and an isolated Chromium executable.
SPDX-License-Identifier: Apache-2.0
"""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pyarrow.parquet as pq
import pyarrow as pa


WORLDS={"clean","critical_edit","missing_evidence"}
VIEWS={"ar_western","ar_eastern"}
SPLITS=("test","challenge")


def rows(release, split, columns):
    paths=sorted((release/"data"/"cases").glob(split+"-*.parquet"))
    if not paths:
        raise ValueError(f"No case shards for {split}")
    for path in paths:
        for batch in pq.ParquetFile(path).iter_batches(batch_size=128,columns=columns):
            yield from batch.to_pylist()


def prepare(release: Path,work: Path,expected_mechanisms: int):
    chosen={}
    for split in SPLITS:
        for row in rows(release,split,["case_id","family_id","world","view","mechanism"]):
            if row["world"]!="clean" or row["view"]!="ar_western":
                continue
            key=(split,row["mechanism"])
            rank=hashlib.sha256(("arb-visual-v1:"+row["family_id"]).encode()).hexdigest()
            if key not in chosen or rank<chosen[key][0]:
                chosen[key]=(rank,row["family_id"])
    mechanisms={mechanism for _,mechanism in chosen}
    if len(mechanisms)!=expected_mechanisms or len(chosen)!=expected_mechanisms*len(SPLITS):
        raise ValueError(f"Selection needs one family per mechanism/split: got {len(chosen)} groups and {len(mechanisms)} mechanisms")
    selected={value[1] for value in chosen.values()}
    cases={}
    for split in SPLITS:
        for row in rows(release,split,["case_id","family_id","world","view","mechanism","question","documents"]):
            if row["family_id"] not in selected or row["world"] not in WORLDS or row["view"] not in VIEWS:
                continue
            if row["case_id"] in cases:
                raise ValueError("Repeated case ID in selected source rows")
            cases[row["case_id"]]={**row,"split":split}
    expected_cases=len(selected)*len(WORLDS)*len(VIEWS)
    if len(cases)!=expected_cases:
        raise ValueError(f"Expected {expected_cases} visual packets, got {len(cases)}")
    observed=Counter((r["family_id"],r["world"],r["view"]) for r in cases.values())
    if any(count!=1 for count in observed.values()):
        raise ValueError("Repeated controlled visual world/view")
    canonical={}
    for split in SPLITS:
        path=release/"specs"/(split+".jsonl.gz")
        if path.exists():
            stream=gzip.open(path,"rt",encoding="utf-8")
        else:
            stream=(release/"specs"/(split+".jsonl")).open(encoding="utf-8")
        with stream:
            for line in stream:
                value=json.loads(line)
                if value["case_id"] in cases:
                    canonical[value["case_id"]]=value["documents"]
    if set(canonical)!=set(cases):
        raise ValueError("Selected packets are not fully covered by canonical specs")
    work.mkdir(parents=True,exist_ok=True)
    jobs=work/"render_jobs.jsonl"
    document_count=0
    with jobs.open("w",encoding="utf-8") as output:
        for case_id,row in sorted(cases.items()):
            spec_docs={d["doc_id"]:d for d in canonical[case_id]}
            if set(spec_docs)!={d["doc_id"] for d in row["documents"]}:
                raise ValueError("Canonical/visible document IDs differ")
            documents=[]
            for doc in row["documents"]:
                fields=spec_docs[doc["doc_id"]]["fields"]
                documents.append({"doc_id":doc["doc_id"],"title":doc["title"],"text":doc["text"],
                                  "expected_fields":[{"id":f["id"],"row_id":f.get("row_id","")} for f in fields]})
            document_count+=len(documents)
            # Do not pass canonical values, roles, gold outputs or edit metadata
            # into the browser renderer. Page HTML uses visible text only.
            job={k:row[k] for k in ("case_id","family_id","world","view","mechanism","question","split")}
            job["documents"]=documents
            output.write(json.dumps(job,ensure_ascii=False,separators=(",",":"))+"\n")
    selection={"selection_method":"Minimum SHA256('arb-visual-v1:'+family_id) within mechanism and test/challenge split",
               "family_count":len(selected),"packet_count":len(cases),"expected_page_count":document_count,
               "worlds":sorted(WORLDS),"views":sorted(VIEWS),
               "families":[{"split":s,"mechanism":m,"family_id":v[1],"selection_hash":v[0]} for (s,m),v in sorted(chosen.items())],
               "jobs_sha256":hashlib.sha256(jobs.read_bytes()).hexdigest(),
               "scope":"A bounded controlled visual subset of existing text cases. Packets/worlds/views are related within generated families, not independent transactions.",
               "page_inputs":"Already-visible document ID, title, text and field markers; canonical values/roles/gold/mechanism/world are never used in page HTML."}
    return jobs,selection


def export_pages(release: Path,output: Path,work: Path,manifest: dict,keep_pngs=False):
    """Embed each page image once, retaining private PNGs for visual inspection."""
    from datasets import Features,Image,Value
    features=Features({
        "page_id":Value("string"),"case_id":Value("string"),"family_id":Value("string"),
        "doc_id":Value("string"),"title":Value("string"),"page_no":Value("int32"),
        "image":Image(),"field_boxes_json":Value("string"),"text":Value("string"),
        "question":Value("string"),"pdf_path":Value("string"),
    })
    schema=features.arrow_schema
    destination=release/"data"/"pages"
    destination.mkdir(parents=True,exist_ok=True)
    for old in destination.glob("*.parquet"):
        old.unlink()
    buffers={};writers={};counts=Counter();files=[]
    try:
        for packet in manifest["packets"]:
            split=packet["split"]
            if split not in writers:
                target=destination/(split+"-00000.parquet")
                writers[split]=pq.ParquetWriter(target,schema,compression="zstd")
                files.append(target.relative_to(release).as_posix());buffers[split]=[]
            packet_dir=output/"packets"/packet["case_id"]
            visible=json.loads((packet_dir/"visible_text.json").read_text(encoding="utf-8"))
            boxes=json.loads((packet_dir/"field_boxes.json").read_text(encoding="utf-8"))
            docs={d["doc_id"]:d for d in visible["documents"]}
            by_doc={p["doc_id"]:p for p in boxes["pages"]}
            for number,page in enumerate(packet["pages"],1):
                doc_id=page["doc_id"];page_id=hashlib.sha256(("arb-page-v1:"+packet["case_id"]+":"+doc_id).encode()).hexdigest()[:24]
                png=packet_dir/(doc_id+".png")
                cached=work/"pngs"/packet["case_id"]/(doc_id+".png")
                image_bytes=(png if png.exists() else cached).read_bytes()
                if hashlib.sha256(image_bytes).hexdigest()!=page["image_sha256"]:
                    raise ValueError("Rendered PNG checksum changed before embedding")
                pboxes=by_doc[doc_id]
                box_value={"semantics":boxes["box_semantics"],"width":pboxes["width"],"height":pboxes["height"],"fields":pboxes["fields"]}
                buffers[split].append({"page_id":page_id,"case_id":packet["case_id"],"family_id":packet["family_id"],
                    "doc_id":doc_id,"title":docs[doc_id]["title"],"page_no":number,
                    "image":{"bytes":image_bytes,"path":None},"field_boxes_json":json.dumps(box_value,ensure_ascii=False,separators=(",",":")),
                    "text":docs[doc_id]["text"],"question":visible["question"],
                    "pdf_path":(packet_dir/"packet.pdf").relative_to(release).as_posix()})
                counts[split]+=1
                if len(buffers[split])>=40:
                    writers[split].write_table(pa.Table.from_pylist(buffers[split],schema=schema),row_group_size=40)
                    buffers[split].clear()
                page["page_id"]=page_id
                pboxes["page_id"]=page_id
                if not keep_pngs:
                    cached.parent.mkdir(parents=True,exist_ok=True)
                    if png.exists():
                        shutil.move(str(png),str(cached))
                    page.pop("image",None);pboxes.pop("image",None)
                    page["image_config"]="pages";pboxes["image_config"]="pages"
            (packet_dir/"field_boxes.json").write_text(json.dumps(boxes,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        for split,writer in writers.items():
            if buffers[split]:
                writer.write_table(pa.Table.from_pylist(buffers[split],schema=schema),row_group_size=40)
    finally:
        for writer in writers.values():
            writer.close()
    manifest["pages_config"]={"files":files,"split_counts":dict(counts),"images_embedded":True,"duplicate_png_files_public":keep_pngs,
        "image_feature":"Hugging Face Image with embedded PNG bytes; nullable path","one_row_is":"One document page within a repeated controlled packet, not an independent transaction"}
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir",type=Path,required=True)
    parser.add_argument("--output-dir",type=Path)
    parser.add_argument("--work-dir",type=Path,required=True)
    parser.add_argument("--expected-mechanisms",type=int,default=14)
    parser.add_argument("--node-executable",default="node")
    parser.add_argument("--node-modules-dir",type=Path)
    parser.add_argument("--chrome-executable")
    parser.add_argument("--prepare-only",action="store_true")
    parser.add_argument("--keep-pngs",action="store_true",help="Also retain duplicate public PNG files; default keeps them only in the private work directory")
    args=parser.parse_args()
    jobs,selection=prepare(args.release_dir,args.work_dir,args.expected_mechanisms)
    output=args.output_dir or args.release_dir/"visual_subset"
    if args.prepare_only:
        (args.work_dir/"selection_manifest.json").write_text(json.dumps(selection,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(json.dumps({"families":selection["family_count"],"packets":selection["packet_count"],"pages":selection["expected_page_count"],"prepared_only":True}))
        return
    output.mkdir(parents=True,exist_ok=True)
    if not output.resolve().is_relative_to(args.release_dir.resolve()):
        raise ValueError("--output-dir must be inside --release-dir for portable PDF links")
    old_audit=output/"validation_report.json"
    if old_audit.exists():
        old_audit.unlink()
    script=Path(__file__).with_suffix(".cjs")
    fonts=Path(__file__).with_name("fonts")
    command=[args.node_executable,str(script),"--jobs",str(jobs),"--output-dir",str(output),"--fonts-dir",str(fonts)]
    if args.chrome_executable:
        command.extend(["--chrome-executable",args.chrome_executable])
    environment=os.environ.copy()
    if args.node_modules_dir:
        environment["NODE_PATH"]=str(args.node_modules_dir)
    subprocess.run(command,env=environment,check=True)
    manifest=json.loads((output/"render_manifest.json").read_text(encoding="utf-8"))
    if not manifest.get("complete") or manifest["packet_count"]!=selection["packet_count"] or manifest["page_count"]!=selection["expected_page_count"]:
        raise ValueError("Rendered output counts do not match selected source packets")
    manifest=export_pages(args.release_dir,output,args.work_dir,manifest,args.keep_pngs)
    manifest["renderer_code_sha256"]={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__),script)}
    (output/"render_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (output/"selection_manifest.json").write_text(json.dumps(selection,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    shutil.copytree(fonts,output/"fonts",dirs_exist_ok=True)
    (output/"README.md").write_text("""# Controlled visual subset

This is a bounded rendering of existing text cases, with one test and one
challenge family per mechanism and three worlds in two Arabic numeral views.
The selection and rendering manifests give the exact counts and source case IDs.
Repeated representations are not additional independent transactions.

Each packet contains one PDF page per visible source document, the original
visible text, and field-container boxes. PNG bytes are embedded in the `pages`
Parquet configuration under `data/pages/` so users can load images directly.
Individual public PNG files are omitted by default to avoid duplicate image
payloads; the renderer keeps inspection copies in its private work directory.
Every page is marked as
synthetic. Page HTML never receives gold outputs, mechanisms, world names,
canonical fact values or internal document roles. The two numeral views use the
same original Arabic text representations as the text dataset.

Field boxes come from Chromium DOM containers at one CSS pixel per PNG pixel;
they are not human text-region annotations or individual-glyph polygons. PDF
counterparts are page-coordinate scalings of those boxes. The manifests record
font hashes and the actual Chromium version. Exact cross-platform raster or PDF
byte identity is not asserted. Numeric/date/identifier tokens use LTR isolation
with directional override, and the renderer checks character positions to avoid
reversing Arabic-Indic ISO date components. Noto fonts are included under OFL 1.1
in fonts/.
""",encoding="utf-8")
    print(json.dumps({"families":manifest["family_count"],"packets":manifest["packet_count"],"pages":manifest["page_count"],"fields":manifest["field_count"]}))


if __name__=="__main__":
    main()
