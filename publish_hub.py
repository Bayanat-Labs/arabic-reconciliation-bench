#!/usr/bin/env python3
"""Upload a completed release, then optionally make the staged repositories public.

Uses normal huggingface_hub authentication without reading or printing tokens.
SPDX-License-Identifier: Apache-2.0
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from huggingface_hub import DatasetCard,HfApi


def check_manifest(root):
    manifest=root/'SHA256SUMS'
    checked=set()
    for line in manifest.read_text().splitlines():
        digest,name=line.split('  ',1)
        path=root/name
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise ValueError(f'Frozen artifact changed: {name}')
        checked.add(name)
    actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p.name!='SHA256SUMS' and '.cache' not in p.parts}
    if actual!=checked:
        raise ValueError('Manifest does not cover exactly the release files')
    return len(checked)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--release-dir',type=Path,required=True)
    p.add_argument('--demo-dir',type=Path,required=True)
    p.add_argument('--repo-id',default='Bayanat-Labs/arabic-reconciliation-bench')
    p.add_argument('--receipt',type=Path,required=True)
    p.add_argument('--publish',action='store_true',help='Make completed staged dataset and static Space public')
    a=p.parse_args();count=check_manifest(a.release_dir)
    DatasetCard.load(a.release_dir/'README.md').validate()
    if 'No measured model results have been supplied' in (a.release_dir/'README.md').read_text():
        raise ValueError('Dataset card is missing measured local-model results')
    if 'MEASURED LOCAL RUNS' not in (a.demo_dir/'index.html').read_text():
        raise ValueError('Demo is missing the completed actual-results table')
    api=HfApi()
    for kind in ('dataset','space'):
        options={'space_sdk':'static'} if kind=='space' else {}
        api.create_repo(repo_id=a.repo_id,repo_type=kind,private=True,exist_ok=True,**options)
    dataset=api.upload_folder(repo_id=a.repo_id,repo_type='dataset',folder_path=a.release_dir,
        commit_message='Release v0.1.0: audited cases, paired comparisons, Arabic pages and measured baselines',ignore_patterns=['.cache/**'])
    space=api.upload_folder(repo_id=a.repo_id,repo_type='space',folder_path=a.demo_dir,
        commit_message='Release offline evidence explorer with measured local-model results',ignore_patterns=['.cache/**'])
    # Publication follows successful complete uploads, never an empty repository.
    if a.publish:
        api.update_repo_settings(a.repo_id,repo_type='dataset',private=False)
        api.update_repo_settings(a.repo_id,repo_type='space',private=False)
        for kind,commit in (('dataset',dataset.oid),('space',space.oid)):
            api.create_tag(a.repo_id,tag='v0.1.0',repo_type=kind,revision=commit,exist_ok=True)
    receipt={'repo_id':a.repo_id,'published':a.publish,'dataset_commit':dataset.oid,
        'space_commit':space.oid,'dataset_files_verified':count,
        'dataset_url':f'https://huggingface.co/datasets/{a.repo_id}',
        'space_url':f'https://huggingface.co/spaces/{a.repo_id}'}
    a.receipt.parent.mkdir(parents=True,exist_ok=True)
    a.receipt.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))

if __name__=='__main__':main()
