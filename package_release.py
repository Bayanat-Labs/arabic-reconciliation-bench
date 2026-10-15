#!/usr/bin/env python3
"""Package completed, audited artifacts without credentials or model weights.

This command is intentionally strict: it refuses incomplete evaluations/audits.
SPDX-License-Identifier: Apache-2.0
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def copy_tree(source, destination):
    for path in sorted(source.rglob('*')):
        if path.is_file() and not any(x in {'__pycache__', '.DS_Store', 'node_modules', '.git'} for x in path.parts):
            copy(path, destination/path.relative_to(source))


def checksums(root):
    lines=[]
    for path in sorted(root.rglob('*')):
        if path.is_file() and path.name != 'SHA256SUMS' and not any(x in {'.git','.cache','__pycache__','node_modules','.DS_Store'} for x in path.relative_to(root).parts):
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            lines.append(f'{digest}  {path.relative_to(root).as_posix()}')
    (root/'SHA256SUMS').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return len(lines)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--release-dir',type=Path,required=True)
    p.add_argument('--model-dir',type=Path,required=True)
    p.add_argument('--heuristic-dir',type=Path,required=True)
    p.add_argument('--test-dir',type=Path,required=True)
    p.add_argument('--validation',type=Path,required=True)
    p.add_argument('--github-dir',type=Path,required=True)
    a=p.parse_args();r=a.release_dir;s=Path(__file__).resolve().parent;g=a.github_dir
    # Validation schemas are deliberately tested for a positive pass, never
    # inferred from the mere presence of a report filename.
    validation=read(a.validation)
    visual=read(r/'visual_subset/validation_report.json')
    tests=read(a.test_dir/'test-summary.json')
    models=read(a.model_dir/'compact_results.json')
    if len(models.get('models',[]))!=1 or any(not x['coverage']['complete'] for x in models['models']):
        raise ValueError('The initial release requires its completed local Qwen baseline')
    for model in models['models']:
        for name,digest in model['artifact_sha256'].items():
            path=a.model_dir/model['run_directory']/name
            if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
                raise ValueError(f'Model artifact changed: {path.name}')
    # Public core hashes must still match the generation provenance.
    stats=read(r/'statistics.json')
    for name,digest in stats['code_sha256'].items():
        if hashlib.sha256((s/name).read_bytes()).hexdigest()!=digest:
            raise ValueError(f'Frozen generation code changed: {name}')
    if validation.get('status')!='passed':
        raise ValueError('Core audit did not pass')
    for name,digest in validation['input_sha256'].items():
        if hashlib.sha256((r/name).read_bytes()).hexdigest()!=digest:
            raise ValueError(f'Audited input changed: {name}')
    if hashlib.sha256((s/'verify.py').read_bytes()).hexdigest()!=validation['verifier_sha256']:
        raise ValueError('Independent verifier changed after the audit')
    if visual.get('status')!='passed':
        raise ValueError('Visual audit did not pass')
    if not tests.get('successful'):
        raise ValueError('Tests did not pass')
    # Copy original code, font notices and reproduction instructions to the Hub.
    if (r/'code').exists():shutil.rmtree(r/'code')
    copy_tree(s,r/'code')
    copy(s/'DATA_LICENSE.txt',r/'LICENSE')
    copy(a.validation,r/'reports/validation.json')
    copy(a.test_dir/'test-summary.json',r/'reports/tests.json')
    copy_tree(a.model_dir,r/'baselines/local_models')
    copy_tree(a.heuristic_dir,r/'baselines/heuristics')
    copy(a.model_dir/'baseline_report.json',r/'reports/model_results.json')
    copy(a.model_dir/'compact_results.json',r/'reports/model_results_compact.json')
    results=(a.model_dir/'RESULTS.md').read_text()
    # Preserve the untouched report next to its raw artifacts, and provide a
    # convenient root-level reading copy whose relative links remain valid.
    for name in ('compact_results.json','baseline_report.json'):
        results=results.replace(f']({name})',f'](baselines/local_models/{name})')
    if (a.model_dir/'FAILURE_ANALYSIS.md').exists():
        results+='\n[Inspect deterministic error examples and exact visible inputs](baselines/local_models/FAILURE_ANALYSIS.md).\n'
    (r/'RESULTS.md').write_text(results,encoding='utf-8')
    (r/'baselines/README.md').write_text('''# Reproducible baselines

`local_models/` contains complete actual runs on the preselected 14-family test
sample (168 correlated views per model), including prompts/protocol hashes,
original responses, normalized predictions and scorer reports. See its
`RESULTS.md` and the exact local-model digests. No weights are redistributed.

`heuristics/` contains full-suite predictions and scores. The text parser plus
formal executor is a controlled-format symbolic ceiling, not a general ML
baseline or a production invoice parser. The fixed prior is a sanity check.

Results are diagnostic measurements on original synthetic controlled templates.
They are not human accounting validation or evidence of production readiness.
''',encoding='utf-8')
    # The GitHub repository keeps source and compact results; all large data,
    # page images, PDFs and full prediction traces live in the linked Hub repo.
    g.mkdir(parents=True,exist_ok=True)
    copy_tree(s,g)
    if (g/'github').exists():
        copy_tree(g/'github/workflows',g/'.github/workflows')
        shutil.rmtree(g/'github')
    for name in ('RELATED_WORK.md','NOTICE.md','CITATION.cff','RESULTS.md','statistics.json'):
        copy(r/name,g/name)
    github_results=(g/'RESULTS.md').read_text()
    github_results=github_results.replace('](baselines/local_models/','](https://huggingface.co/datasets/Bayanat-Labs/arabic-reconciliation-bench/blob/main/baselines/local_models/')
    (g/'RESULTS.md').write_text(github_results)
    card=(r/'README.md').read_text()
    card=re.sub(r'\A---\n.*?\n---\n','',card,flags=re.S)
    card=re.sub(r'\]\(code/([^)]*)\)',r'](\1)',card)
    card=card.replace('`LICENSE`, `code/LICENSE`','`DATA_LICENSE.txt`, `LICENSE`')
    card=card.replace('code/','')
    # Data/reports are deliberately not duplicated in GitHub.
    for prefix in ('data/','specs/','reports/','visual_subset/','baselines/'):
        card=card.replace(f']({prefix}',f'](https://huggingface.co/datasets/Bayanat-Labs/arabic-reconciliation-bench/blob/main/{prefix}')
    card=card.replace('](LICENSE)','](DATA_LICENSE.txt)')
    intro='''[Dataset on Hugging Face](https://huggingface.co/datasets/Bayanat-Labs/arabic-reconciliation-bench) · [Interactive evidence explorer](https://huggingface.co/spaces/Bayanat-Labs/arabic-reconciliation-bench) · [Reproduce the release](REPRODUCING.md)

'''
    (g/'README.md').write_text(intro+card.lstrip(),encoding='utf-8')
    for source,name in ((a.validation,'validation.json'),(a.test_dir/'test-summary.json','tests.json'),(a.model_dir/'compact_results.json','model_results_compact.json'),(a.heuristic_dir/'heuristic_baselines.json','heuristic_baselines.json')):
        copy(source,g/'reports'/name)
    (g/'.gitignore').write_text('''__pycache__/
*.py[cod]
.venv/
node_modules/
release/
render-work/
model-runs/
*.partial
.DS_Store
''')
    (g/'baselines/README.md').parent.mkdir(exist_ok=True)
    (g/'baselines/README.md').write_text('Full prediction files, manifests and original model responses are published with the [dataset baselines](https://huggingface.co/datasets/Bayanat-Labs/arabic-reconciliation-bench/tree/main/baselines). Compact results are in `../RESULTS.md` and `../reports/`.\n')
    total=checksums(r);gh_total=checksums(g)
    print(json.dumps({'dataset_files':total,'github_files':gh_total,'models':len(models['models']),'ready':True}))

if __name__=='__main__':main()
