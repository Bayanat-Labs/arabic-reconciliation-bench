#!/usr/bin/env python3
"""Render completed measured local baselines; never synthesize missing results."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics


def percent(value):
    return '—' if value is None else f'{100*value:.1f}%'


def estimate(value, interval):
    point = percent(value)
    return point if not interval else f"{point} [{100*interval['low']:.1f}, {100*interval['high']:.1f}]"


def display(model):
    if model == 'qwen2.5:3b':
        return 'Qwen2.5 3B (local GGUF)'
    if 'Fanar-1-9B' in model:
        return 'Fanar-1 9B (local GGUF)'
    return model


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-dir',type=Path,required=True)
    p.add_argument('--release-dir',type=Path,required=True)
    p.add_argument('--output-dir',type=Path)
    args=p.parse_args()
    root=args.run_dir;out=args.output_dir or root
    report_path=root/'baseline_report.json'
    source=json.loads(report_path.read_text())
    smoke=json.loads((root/'protocol_smoke.json').read_text())
    if not smoke.get('literal_control_passed') or smoke.get('actual',{}).get('contract_net_minor')!=12345:
        raise ValueError('Separate literal numeric schema control has not passed')
    sample=source['sample']
    excluded=json.loads((root/'excluded_exploration.json').read_text())
    expected_models={'qwen2.5:3b'}
    if {row['model'] for row in source['models']}!=expected_models:
        raise ValueError('Final narrative requires exactly the completed Qwen baseline; excluded exploratory models cannot be scored here')
    if sample['family_count']!=14 or sample['case_count']!=168:
        raise ValueError('This final-results narrative is scoped to the preselected 14-family, 168-view protocol')
    import pyarrow.parquet as pq
    wanted=set(sample['case_ids']);seen=set();gold_null=0;missing_roles=Counter();gold_classes=Counter();views_selected=Counter()
    title_roles={'سياسة المطابقة الخاصة بهذه الحالة':'policy','أمر الشراء':'po','فاتورة المورد':'invoice','سجل استلام البضائع':'receipts','سجل المرتجعات':'returns','سجل الفواتير السابقة':'history','سجل تعديلات الأسعار':'amendments'}
    for item in sample['test_files']:
        path=args.release_dir/item['path']
        if sha(path)!=item['sha256']:
            raise ValueError('Published test data differ from the measured input fingerprint')
        for batch in pq.ParquetFile(path).iter_batches(columns=['case_id','world','view','gold_decision','gold_contract_net_minor','documents']):
            for record in batch.to_pylist():
                if record['case_id'] not in wanted:continue
                if record['case_id'] in seen:raise ValueError('Duplicate selected row')
                seen.add(record['case_id']);gold_null+=record['gold_contract_net_minor'] is None;gold_classes[record['gold_decision']]+=1;views_selected[record['view']]+=1
                if record['world']=='missing_evidence' and record['view']=='ar_western':
                    missing_roles.update(set(title_roles.values())-{title_roles[d['title']] for d in record['documents']})
    if seen!=wanted:raise ValueError('Selected public rows missing from the release')
    composition={'gold_amount_numeric_cases':len(seen)-gold_null,'gold_amount_null_cases':gold_null,'omitted_role_families':dict(sorted(missing_roles.items())),'gold_decision_cases':dict(sorted(gold_classes.items())),'view_cases':dict(sorted(views_selected.items()))}
    model_rows=[]
    for model in source['models']:
        coverage=model['coverage']
        if not coverage['complete'] or coverage['completed_cases']!=sample['case_count']:
            raise ValueError(f"Cannot describe incomplete run as a final baseline: {model['model']}")
        report=model['score_report']
        if not report or report['metrics']['cases']!=sample['case_count'] or report['selected_families']!=sample['family_count']:
            raise ValueError('Scorer universe does not match selected complete families')
        folder=root/model['run_directory']
        manifest=json.loads((folder/'run_manifest.json').read_text())
        if not manifest.get('constrained_decoding') or manifest['binding']['format']!='schema':
            raise ValueError('This results template requires the preselected schema-constrained protocol')
        if manifest['requested_sample']['case_ids']!=sample['case_ids'] or manifest['binding']['dataset_fingerprint']!=sample['dataset_fingerprint']:
            raise ValueError('Sample/data fingerprint mismatch')
        raw=[json.loads(line) for line in (folder/'raw_responses.jsonl').read_text().splitlines() if line.strip()]
        latest={r['case_id']:r for r in raw if r['case_id'] in set(sample['case_ids'])}
        timings=[r['wall_seconds'] for r in latest.values()]
        response_stats=[r.get('response') for r in latest.values() if isinstance(r.get('response'),dict)]
        prompt_tokens=[r['prompt_eval_count'] for r in response_stats if 'prompt_eval_count' in r]
        output_tokens=[r['eval_count'] for r in response_stats if 'eval_count' in r]
        token_totals=[r['prompt_eval_count']+r['eval_count'] for r in response_stats if 'prompt_eval_count' in r and 'eval_count' in r]
        official_context=4096 if 'Fanar-1-9B' in model['model'] else 32768 if model['model']=='qwen2.5:3b' else None
        local_source=json.loads((root/'model_source_info.json').read_text()).get(model['model'],{}) if (root/'model_source_info.json').exists() else {}
        local_contexts={k:v for k,v in local_source.get('model_info',{}).items() if k.endswith('.context_length')}
        metrics=report['metrics'];ci=report['confidence_intervals']
        if ci['samples']!=1000 or ci['seed']!=20261015 or ci['confidence_level']!=.95:
            raise ValueError('Bootstrap protocol differs from the preselected final narrative')
        model_rows.append({
            'model':model['model'],'display_name':display(model['model']),
            'model_digest':model['model_digest'],'run_directory':model['run_directory'],
            'cases':metrics['cases'],'families':report['selected_families'],
            'coverage':coverage,'primary':{k:metrics[k] for k in ('decision_exact','amount_exact','issues_exact','core_exact')},
            'evidence_diagnostics':{k:metrics[k] for k in ('evidence_precision','evidence_recall','evidence_f1','evidence_reference_coverage','citations_valid','strict_joint')},
            'schema_valid':metrics['schema_valid'],
            'context':{'configured_num_ctx':manifest['binding']['options']['num_ctx'],'official_source_context':official_context,'local_gguf_context_metadata':local_contexts,'requests_with_reported_token_counts':len(token_totals),'maximum_reported_prompt_plus_generated_tokens':max(token_totals) if token_totals else None,'requests_exceeding_official_source_context':sum(n>official_context for n in token_totals) if official_context else None,'prompts_exceeding_official_source_context':sum(n>official_context for n in prompt_tokens) if official_context else None},
            'per_class':metrics['decision_classification']['per_class'],
            'confusion':metrics['decision_classification']['confusion'],
            'by_view':{k:{m:v[m] for m in ('cases','decision_exact','amount_exact','issues_exact','core_exact','strict_joint')} for k,v in report['by']['view'].items()},
            'paired_both_decision':report.get('paired_both_decision',{}),
            'paired_both_core':report.get('paired_both_core',{}),
            'paired_both_joint':report['paired_both_joint'],
            'all_view_joint':report['all_view_joint'],'all_family_joint':report['all_family_joint'],
            'confidence_intervals':ci,'scorer':report.get('scorer'),
            'timing':{'latest_attempt_wall_seconds_total':sum(timings),'request_wall_seconds_mean':statistics.mean(timings),'request_wall_seconds_median':statistics.median(timings),
                      'prompt_tokens_min':min(prompt_tokens) if prompt_tokens else None,'prompt_tokens_max':max(prompt_tokens) if prompt_tokens else None,
                      'output_tokens_min':min(output_tokens) if output_tokens else None,'output_tokens_max':max(output_tokens) if output_tokens else None},
            'protocol':{'binding':manifest['binding'],'runner_code_sha256':manifest['runner_code_sha256'],
                        'constrained_decoding':manifest['constrained_decoding']},
            'artifact_sha256':{name:sha(folder/name) for name in ('run_manifest.json','raw_responses.jsonl','predictions.jsonl','score_report.json')},
        })
    base_binding=model_rows[0]['protocol']['binding']
    comparison_keys=('dataset_fingerprint','model_input_code_sha256','options','format','truncate','shift','output_schema_sha256','sample_seed','ollama_version')
    if base_binding['options']!={'temperature':0,'seed':20261015,'num_ctx':8192,'num_predict':2048} or base_binding['truncate'] or base_binding['shift']:
        raise ValueError('Generation settings differ from the preselected final narrative')
    for row in model_rows[1:]:
        for key in comparison_keys:
            if row['protocol']['binding'][key]!=base_binding[key]:
                raise ValueError(f'Model protocols differ at {key}')
    payload={
        'schema_version':'1.0','source_baseline_report_sha256':sha(report_path),
        'dataset_fingerprint':sample['dataset_fingerprint'],'sample_seed':sample['sample_seed'],
        'selection':sample['method'],'split':sample['split'],
        'families':sample['family_count'],'cases_per_model':sample['case_count'],'sample_composition':composition,
        'interpretation':'Small deterministic stratified controlled synthetic test sample. Complete correlated family views are not independent observations. No ranking or production generalization claim.',
        'constrained_decoding':True,'models':model_rows,'excluded_exploration':excluded,
        'separate_schema_smoke':{'model':smoke['model'],'model_digest':smoke['model_digest'],'literal_control_passed':smoke['literal_control_passed'],'requested_amount':12345,'benchmark_included':False,'record_sha256':sha(root/'protocol_smoke.json')},
        'machine_info':json.loads((root/'machine_info.json').read_text()) if (root/'machine_info.json').exists() else None,
    }
    out.mkdir(parents=True,exist_ok=True)
    (out/'compact_results.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
    card={'families':sample['family_count'],'cases_per_model':sample['case_count'],'split':'test','sample_composition':composition,'schema_constrained_decoding':True,'rows':[{'model':row['display_name'],**row['primary'],'decision_95ci':row['confidence_intervals']['intervals']['decision_exact'],'core_95ci':row['confidence_intervals']['intervals']['core_exact'],'evidence_mean_precision':row['evidence_diagnostics']['evidence_precision'],'evidence_mean_recall':row['evidence_diagnostics']['evidence_recall'],'strict_joint':row['evidence_diagnostics']['strict_joint'],'context':row['context']} for row in model_rows]}
    (out/'card_table.json').write_text(json.dumps(card,ensure_ascii=False,indent=2)+'\n')
    rows=[]
    for row in model_rows:
        m=row['primary'];intervals=row['confidence_intervals']['intervals']
        rows.append('| '+row['display_name']+' | '+estimate(m['decision_exact'],intervals.get('decision_exact'))+' | '+percent(m['amount_exact'])+' | '+percent(m['issues_exact'])+' | '+estimate(m['core_exact'],intervals.get('core_exact'))+' |')
    text='''# Measured local-model results

The sole published language-model baseline is a completed local Qwen2.5 3B run on **{families} deterministic test families, {cases} case views**, with one family from each of the 14 mechanisms. Each family supplies three worlds and four controlled views. The effective number of independent generated family clusters is {families}, not {cases}; this is a small diagnostic sample, not a leaderboard, model ranking or production accuracy estimate.

Qwen used **fixed, gold-independent JSON-schema constrained decoding**. Consequently, schema-valid output measures operation under that constraint, not unconstrained JSON compliance. No answer repair or repeat request for a wrong/schema-invalid answer was used. All original responses remain available. A separate gold-independent Fanar smoke control requested the literal amount `12345` with the same schema/options and returned it exactly, confirming numeric representability in that separate Fanar runtime call. This was a Fanar control, not a Qwen control or a completed Fanar benchmark. This single control is excluded from all benchmark counts and scores; its exact record is `protocol_smoke.json` in the local-model bundle. It does not test document reasoning.

## Decision and numeric results

Core exact requires the decision, nominal contract amount and complete issue set all to be correct. It has no evidence-citation requirement. Amount exact is evaluated against the selected nominal contract targets; it is not payable-amount accuracy. {amount_scope} Brackets are 95% family-cluster percentile-bootstrap intervals in percentage points (1,000 resamples, seed 20261015); the point estimates use all selected case views. These intervals describe resampling of this small synthetic sample and do not establish population or deployment validity. One selected family per mechanism cannot estimate within-mechanism variation.

| Local model | Decision exact [95% CI] | Amount exact | Issue-set exact | Core exact [95% CI] |
|---|---:|---:|---:|---:|
{primary}

## Evidence diagnostics

Evidence precision/recall/F1 below are means of per-case agreement with the executable reference read trace. The trace is not a human-certified or uniquely minimal proof. Reference coverage can be inflated by citing every field. Strict joint combines core exact, full reference coverage and no nonexistent citations; extra valid citations are allowed. Citation and core correctness should therefore be inspected separately.

| Local model | Mean ref. precision | Mean ref. recall | Mean ref. F1 | Full ref. coverage | Strict joint |
|---|---:|---:|---:|---:|---:|
{evidence}

## Decision classes

All metrics use the explicitly selected Qwen case universe. An undefined precision is shown as an em dash when the model never predicts that class.

| Local model | Gold class | Support | Predicted | Precision | Recall | F1 |
|---|---|---:|---:|---:|---:|---:|
{classes}

## Controlled views

Each view contains the same 42 family-world combinations. English is an aligned controlled rendering; this is not a natural-language distribution comparison or a general Arabic-vs-English performance claim.

| Local model | View | Cases | Decision exact | Core exact |
|---|---|---:|---:|---:|
{views}

## Matched comparisons

Paired-both correctness requires both members to be correct; unchanged wrong answers do not count as robust correctness. Sensitivity pairs compare clean packets with a changed fact or omitted document. Invariance pairs compare controlled representations of the same facts. All pairs share the same small set of family clusters.

| Local model | Pair axis | Pairs | Both decisions correct | Both core answers correct | Both strict-joint correct |
|---|---|---:|---:|---:|---:|
{pairs}

## Context scope and model provenance

The published Qwen run uses a configured `num_ctx=8192`, within the **32,768-token** context declared by its official model card and local GGUF metadata. Reported prompt tokens plus generated tokens are audited below. No Qwen request exceeds that source-model limit. This controlled run does not establish general model capability.

| Local model | Official source context | Local GGUF declaration | Configured context | Max reported prompt + output | Requests above source context |
|---|---:|---:|---:|---:|---:|
{contexts}

{excluded_scope}

The source [Qwen2.5 3B Instruct card](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct) and exact [Qwen Research License](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct/blob/main/LICENSE) apply; this 3B model is not Apache-2.0. The separate Fanar control used the [yasserrmd GGUF conversion](https://huggingface.co/yasserrmd/Fanar-1-9B-Instruct-gguf) of [QCRI/Fanar-1-9B-Instruct](https://huggingface.co/QCRI/Fanar-1-9B-Instruct), whose official card identifies Apache-2.0. Source metadata is separately recorded in `model_source_info.json`.

No weights or model implementation are distributed. These responses are research/evaluation traces, excluded from the benchmark gold and training tables. Downstream model/output use must follow source-model terms, including Qwen conditions for creating, training or improving a distributed AI model with its outputs. Dataset and code licenses do not replace model-specific terms.

## Reproducible execution

Selection uses `{seed}`: SHA-256 family ranking within each mechanism and mechanism round-robin ordering. The complete-family sample was chosen before outputs were inspected and was not replaced after observing results. Prompts contain only the public question and visible document `doc_id`, `title` and `text`, plus the standard answer contract. Gold answers, mechanism, view, world and canonical fields are excluded. Weights were already installed locally; the runner did not pull models or call paid/cloud inference.

Saved requests, weight digests and options reproduce the disclosed setup; seeded GPU inference need not be bit-identical across hardware or Ollama versions.

Fixed options: temperature 0; seed 20261015; context 8192; maximum generated tokens 2048; `truncate=false`; `shift=false`; Ollama {ollama}. Context/transport failures and invalid/missing outputs count as failures. Model weights are not distributed and retain their original licenses.

| Local model | Completed / requested | Valid under schema constraint | Latest-attempt transport failures | Mean / median request seconds | Prompt token range | Output token range |
|---|---:|---:|---:|---:|---:|---:|
{execution}

The execution table uses the latest retained attempt per case for timings and transport failures; raw checkpoints preserve every earlier attempt, if any. Request timings include local desktop contention and model loading where applicable; they are not a controlled hardware-throughput benchmark. Machine metadata, when recorded, is available in `machine_info.json` and the compact JSON.

Exact model tags and digests:

{digests}

The machine-readable [compact_results.json](compact_results.json) includes exact hashes, protocol bindings, confusion matrices, per-view scores and cluster intervals. [baseline_report.json](baseline_report.json) contains complete scorer reports. Each model directory contains its exact `run_manifest.json`, `raw_responses.jsonl`, `predictions.jsonl`, and `score_report.json`. The scorer hash is recorded in every score report. Earlier transport/protocol pilots and pre-freeze runs are excluded from these results.

The dataset uses original controlled synthetic templates without native-speaker/accountant validation. These measurements cannot establish real-record reconciliation accuracy, fraud detection, accounting compliance, or business readiness. No model ranking or claim about general model quality follows from this small sample.
'''
    evidence=[];classes=[];views=[];pairs=[];execution=[];digests=[];contexts=[]
    for row in model_rows:
        name=row['display_name'];e=row['evidence_diagnostics'];c=row['coverage'];t=row['timing'];ctx=row['context']
        local_declared=', '.join(str(x) for x in ctx['local_gguf_context_metadata'].values()) or 'unrecorded'
        contexts.append(f"| {name} | {ctx['official_source_context']} | {local_declared} | {ctx['configured_num_ctx']} | {ctx['maximum_reported_prompt_plus_generated_tokens']} | {ctx['requests_exceeding_official_source_context']} / {ctx['requests_with_reported_token_counts']} |")
        evidence.append('| '+name+' | '+' | '.join(percent(e[k]) for k in ('evidence_precision','evidence_recall','evidence_f1','evidence_reference_coverage','strict_joint'))+' |')
        for label,m in sorted(row['per_class'].items()):
            classes.append(f"| {name} | `{label}` | {m['support']} | {m['predicted']} | {percent(m['precision'])} | {percent(m['recall'])} | {percent(m['f1'])} |")
        for label,m in sorted(row['by_view'].items()):
            views.append(f"| {name} | `{label}` | {m['cases']} | {percent(m['decision_exact'])} | {percent(m['core_exact'])} |")
        for axis,m in sorted(row['paired_both_joint'].items()):
            if axis=='all':continue
            d=row['paired_both_decision'].get(axis,{}).get('rate');v=row['paired_both_core'].get(axis,{}).get('rate')
            pairs.append(f"| {name} | `{axis}` | {m['pairs']} | {percent(d)} | {percent(v)} | {percent(m['rate'])} |")
        execution.append(f"| {name} | {c['completed_cases']} / {c['requested_cases']} | {c['schema_valid_outputs']} / {c['requested_cases']} | {c['transport_failures']} | {t['request_wall_seconds_mean']:.2f} / {t['request_wall_seconds_median']:.2f} | {t['prompt_tokens_min']}–{t['prompt_tokens_max']} | {t['output_tokens_min']}–{t['output_tokens_max']} |")
        digests.append(f"- `{row['model']}` — `{row['model_digest']}`; artifacts in `{row['run_directory']}/`.")
    excluded_scope=(f"An exploratory Fanar GGUF run was stopped after {excluded['completed_requests']} requests because its local 8,192-token metadata conflicts with the official [4,096-token source context](https://huggingface.co/QCRI/Fanar-1-9B-Instruct/blob/main/config.json); {excluded['requests_exceeding_official_source_context']} reported prompt-plus-output totals exceeded 4,096. It is excluded from the published benchmark aggregate and has no published aggregate score. Partial inference checkpoints are preserved locally outside this release. The separate literal Fanar control and source provenance remain explicitly labeled as controls. See `EXCLUDED_EXPLORATION.md` in the local-model bundle.")
    amount_scope=(f"All {composition['gold_amount_numeric_cases']} selected targets are numeric; this subset contains no `null` amount targets and does not measure correct abstention on unknown amounts." if not gold_null else f"This subset has {composition['gold_amount_numeric_cases']} numeric and {gold_null} `null` amount targets.")
    omission_scope=', '.join(f'{role}: {count} families' for role,count in composition['omitted_role_families'].items())
    amount_scope+=' Omitted required documents in the selected families are '+omission_scope+'. This composition is a consequence of the preselected deterministic sample, not a result-dependent replacement.'
    text=text.format(families=sample['family_count'],cases=sample['case_count'],primary='\n'.join(rows),evidence='\n'.join(evidence),classes='\n'.join(classes),views='\n'.join(views),pairs='\n'.join(pairs),seed=sample['sample_seed'],ollama=base_binding['ollama_version'],execution='\n'.join(execution),digests='\n'.join(digests),contexts='\n'.join(contexts),excluded_scope=excluded_scope,amount_scope=amount_scope)
    (out/'RESULTS.md').write_text(text)
    print(json.dumps({'models':len(model_rows),'families':sample['family_count'],'cases_per_model':sample['case_count'],'results':str((out/'RESULTS.md').resolve()),'compact':str((out/'compact_results.json').resolve())}))


if __name__=='__main__':main()
