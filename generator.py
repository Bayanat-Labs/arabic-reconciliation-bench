"""Generate original, matched synthetic procurement packets (Apache-2.0)."""
from __future__ import annotations
import argparse,copy,gzip,hashlib,json,random
from collections import Counter,defaultdict
from datetime import date,timedelta
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
from core import ROLES,TITLES,LABELS,QUESTION_AR,QUESTION_EN,compute_gold,rounded_net,render_documents

MECHANISMS=('receipt_quantity','rejected_quantity','return_quantity','pack_conversion','cumulative_billing','price_tolerance','discount','invoice_total','currency','duplicate_invoice','amendment_date','amendment_status','receipt_date','cancellation')
VIEWS=('ar_western','ar_eastern','ar_reordered','en_control')
CASE_SCHEMA=pa.schema([
 ('case_id',pa.string()),('family_id',pa.string()),('world',pa.string()),('view',pa.string()),
 ('language',pa.string()),('digit_script',pa.string()),('mechanism',pa.string()),('style',pa.int32()),
 ('question',pa.string()),('documents',pa.list_(pa.struct([('doc_id',pa.string()),('title',pa.string()),('text',pa.string())]))),
 ('gold_decision',pa.string()),('gold_contract_net_minor',pa.int64()),('gold_issues',pa.list_(pa.string())),('gold_evidence_ids',pa.list_(pa.string()))])
PAIR_SCHEMA=pa.schema([(x,pa.string()) for x in ('pair_id','family_id','case_id_a','case_id_b','relation','axis','edit_json')])

def ident(s):return hashlib.sha256(s.encode()).hexdigest()[:24]
def record(**kw):return {k:str(v).lower() if isinstance(v,bool) else str(v) for k,v in kw.items()}
def doc(role,header,rows):return {'role':role,'header':header,'rows':rows}

def materialize(spec,rng):
    role_ids=list(range(1,len(ROLES)+1));rng.shuffle(role_ids);out=[]
    for role,n in zip(ROLES,role_ids):
        d=spec[role];fields=[];counter=0;doc_id=f'D{n:02d}'
        for row_id,values in [('',d['header'])]+[(f'R{i+1:02d}',r) for i,r in enumerate(d['rows'])]:
            for key,value in values.items():
                counter+=1;fields.append({'id':f'{doc_id}.F{counter:02d}','key':key,'row_id':row_id,'value':str(value),
                                          'label_ar':LABELS[key][0],'label_en':LABELS[key][1]})
        out.append({'doc_id':doc_id,'role':role,'title':TITLES[role][0],'title_en':TITLES[role][1],'fields':fields})
    rng.shuffle(out);return out

def getfield(documents,role,key,row=0):
    d=next(d for d in documents if d['role']==role)
    matches=[f for f in d['fields'] if f['key']==key and (bool(f['row_id']) if row else not f['row_id'])]
    return d,matches[row-1 if row else 0]

def make_family(mechanism,family_id,index,split,rng):
    n=4 if split=='challenge' else rng.choice((2,3))
    inv_date=date(2026,1,1)+timedelta(days=rng.randrange(250))
    earlier=(inv_date-timedelta(days=7)).isoformat();future=(inv_date+timedelta(days=30)).isoformat()
    order='PO-'+ident(family_id+':po')[:10].upper();invoice='INV-'+ident(family_id+':inv')[:10].upper()
    currency=rng.choice(('SAR','AED','QAR','USD'));items=[];receipts=[];returns=[];history=[];amendments=[];invrows=[]
    for i in range(n):
        sku='P-'+ident(family_id+':sku:'+str(i))[:8].upper()
        q=rng.randint(24,64);previous=rng.randint(2,8);returned=rng.randint(1,4);rejected=rng.randint(1,3);margin=rng.randint(5,12)
        price=rng.randint(499,19999);discount=rng.choice((0,125,250,375,500,750))
        pack=12 if mechanism=='pack_conversion' and i==0 else rng.choice((6,10,12,24))
        if mechanism=='pack_conversion' and i==0:
            delivered=(q+previous+returned+margin+pack-1)//pack;rejected=0;unit='pack'
        else:delivered=q+previous+returned+margin+rejected;unit='unit'
        ordered=max(q+previous+200,delivered*pack+50 if unit=='pack' else delivered+50)
        effective=price
        if mechanism in ('amendment_date','amendment_status') and i==0:
            effective=price+max(50,price//4)
            amendments.append(record(amendment_id='AM-'+ident(family_id+str(i))[:8],sku=sku,effective_date=earlier,status='approved',unit_price_minor=effective))
        elif split=='challenge' or i%2==1:
            effective=price+rng.randint(2,10)
            amendments.append(record(amendment_id='AM-'+ident(family_id+str(i))[:8],sku=sku,effective_date=earlier,status='approved',unit_price_minor=effective))
        actual=effective+max(1,effective*2//100) if mechanism=='price_tolerance' and i==0 else effective
        items.append(record(sku=sku,ordered_units=ordered,units_per_pack=pack,unit_price_minor=price,discount_bps=discount))
        invrows.append(record(sku=sku,quantity_units=q,unit_price_minor=actual,discount_bps=discount))
        receipts.append(record(receipt_id='GR-'+ident(family_id+str(i))[:8],sku=sku,date=earlier,quantity=delivered,quantity_unit=unit,rejected_quantity=rejected))
        returns.append(record(return_id='RT-'+ident(family_id+str(i))[:8],sku=sku,date=earlier,quantity_units=returned,status='approved'))
        history.append(record(invoice_id='OLD-'+ident(family_id+str(i))[:8],order_id=order,sku=sku,quantity_units=previous,status='posted'))
    # Genuine distractors under the explicit cutoff/status rules, in every split.
    amendments.append(record(amendment_id='AM-FUT-'+ident(family_id)[:6],sku=items[0]['sku'],effective_date=future,status='draft',unit_price_minor=int(items[0]['unit_price_minor'])*3))
    receipts.append(record(receipt_id='GR-FUT-'+ident(family_id)[:6],sku=items[0]['sku'],date=future,quantity=999,quantity_unit='unit',rejected_quantity=0))
    returns.append(record(return_id='RT-DRAFT-'+ident(family_id)[:6],sku=items[0]['sku'],date=earlier,quantity_units=999,status='draft'))
    history.append(record(invoice_id='VOID-'+ident(family_id)[:6],order_id=order,sku=items[0]['sku'],quantity_units=999,status='void'))
    total=sum(rounded_net(int(r['quantity_units']),int(r['unit_price_minor']),int(r['discount_bps'])) for r in invrows)
    specs={
     'policy':doc('policy',record(price_tolerance_bps=300,receipt_cutoff='invoice_date',required_roles=','.join(ROLES[1:]),accepted_only=True,cumulative_billing=True,approved_amendments_only=True,canceled_orders_forbidden=True),[]),
     'po':doc('po',record(order_id=order,status='active',currency=currency),items),
     'invoice':doc('invoice',record(invoice_id=invoice,order_id=order,date=inv_date.isoformat(),currency=currency,stated_net_minor=total),invrows),
     'receipts':doc('receipts',record(complete=True),receipts),'returns':doc('returns',record(complete=True),returns),
     'history':doc('history',record(complete=True),history),'amendments':doc('amendments',record(complete=True),amendments)}
    clean=materialize(specs,rng);critical=copy.deepcopy(clean)
    focus=compute_gold(clean)['trace']['lines'][0]
    q=int(invrows[0]['quantity_units']);p=int(history[0]['quantity_units']);ret=int(returns[0]['quantity_units']);rej=int(receipts[0]['rejected_quantity']);delivered=int(receipts[0]['quantity'])
    edits={
      'receipt_quantity':('receipts','quantity',1,q+p+ret+rej-1),
      'rejected_quantity':('receipts','rejected_quantity',1,delivered-q-p-ret+1),
      'return_quantity':('returns','quantity_units',1,focus['received_units']-p-q+1),
      'pack_conversion':('po','units_per_pack',1,1),
      'cumulative_billing':('history','quantity_units',1,focus['received_units']-ret-q+1),
      'price_tolerance':('policy','price_tolerance_bps',0,0),
      'discount':('po','discount_bps',1,int(items[0]['discount_bps'])+100),
      'invoice_total':('invoice','stated_net_minor',0,total+rng.randint(1,99)),
      'currency':('invoice','currency',0,'AED' if currency!='AED' else 'SAR'),
      'duplicate_invoice':('history','invoice_id',1,invoice),
      'amendment_date':('amendments','effective_date',1,(inv_date+timedelta(days=1)).isoformat()),
      'amendment_status':('amendments','status',1,'draft'),
      'receipt_date':('receipts','date',1,future),
      'cancellation':('po','status',0,'canceled')}
    role,key,row,new=edits[mechanism];d,field=getfield(critical,role,key,row);old=field['value'];field['value']=str(new)
    edit={'path':f"documents.{d['doc_id']}.fields.{field['id']}.value",'doc_id':d['doc_id'],'field_id':field['id'],'before':old,'after':str(new)}
    missing=copy.deepcopy(clean);removed_role=rng.choice(('po','receipts','returns','history','amendments','policy'))
    removed=next(d for d in missing if d['role']==removed_role);missing.remove(removed)
    worlds={'clean':(clean,None),'critical_edit':(critical,edit),'missing_evidence':(missing,{'removed_doc_id':removed['doc_id'],'removed_role':removed_role})}
    for world,(docs,_) in worlds.items():
        gold=compute_gold(docs)
        if gold['decision']!={'clean':'match','critical_edit':'mismatch','missing_evidence':'insufficient_evidence'}[world]:
            raise ValueError((mechanism,world,gold))
    return worlds

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--families-per-mechanism',type=int,default=400);p.add_argument('--seed',type=int,default=20261015);args=p.parse_args()
    root=args.output;root.mkdir(parents=True,exist_ok=True)
    counts=Counter();split_counts=defaultdict(Counter);mechanism_counts=Counter();evidence_counts=[];spec_handles={};writers={};buffers={};family_counts=Counter()
    for split in ('train','validation','test','challenge'):
        (root/'specs').mkdir(exist_ok=True);spec_handles[split]=gzip.open(root/'specs'/f'{split}.jsonl.gz','wt',encoding='utf-8',compresslevel=6)
        for config,schema in (('cases',CASE_SCHEMA),('pairs',PAIR_SCHEMA)):
            folder=root/'data'/config;folder.mkdir(parents=True,exist_ok=True)
            writers[(config,split)]=pq.ParquetWriter(folder/f'{split}-00000.parquet',schema,compression='zstd');buffers[(config,split)]=[]
    def add(config,split,row):
        buffers[(config,split)].append(row);split_counts[config][split]+=1
        if len(buffers[(config,split)])>=250:
            schema=CASE_SCHEMA if config=='cases' else PAIR_SCHEMA
            writers[(config,split)].write_table(pa.Table.from_pylist(buffers[(config,split)],schema=schema),row_group_size=250);buffers[(config,split)].clear()
    for mechanism in MECHANISMS:
        for i in range(args.families_per_mechanism):
            frac=i/args.families_per_mechanism
            split='train' if frac<.7 else 'validation' if frac<.8 else 'test' if frac<.9 else 'challenge'
            style={'train':i%2,'validation':i%2,'test':2,'challenge':3}[split]
            family=ident(f'arb-v1:{args.seed}:{mechanism}:{i}');rng=random.Random(int(family,16))
            worlds=make_family(mechanism,family,i,split,rng);caseids={};family_counts[split]+=1
            for world,(documents,edit) in worlds.items():
                gold=compute_gold(documents)
                for view in VIEWS:
                    case=ident(family+':'+world+':'+view);caseids[(world,view)]=case
                    visible=render_documents(documents,view,style)
                    row={'case_id':case,'family_id':family,'world':world,'view':view,'language':'en' if view=='en_control' else 'ar',
                         'digit_script':'arabic_indic' if view=='ar_eastern' else 'western','mechanism':mechanism,'style':style,
                         'question':QUESTION_EN if view=='en_control' else QUESTION_AR,'documents':visible,
                         'gold_decision':gold['decision'],'gold_contract_net_minor':gold['contract_net_minor'],
                         'gold_issues':gold['issues'],'gold_evidence_ids':gold['evidence_ids']}
                    add('cases',split,row);counts['cases']+=1;mechanism_counts[mechanism]+=1;evidence_counts.append(len(gold['evidence_ids']))
                    spec={'case_id':case,'family_id':family,'world':world,'view':view,'mechanism':mechanism,'style':style,'split':split,'documents':documents,'gold':gold,'edit':edit}
                    spec_handles[split].write(json.dumps(spec,ensure_ascii=False,separators=(',',':'))+'\n')
                for view,axis in (('ar_eastern','digit_script'),('ar_reordered','document_order'),('en_control','language_control')):
                    a,b=caseids[(world,'ar_western')],caseids[(world,view)]
                    add('pairs',split,{'pair_id':ident(a+b),'family_id':family,'case_id_a':a,'case_id_b':b,'relation':'invariant','axis':axis,'edit_json':'{}'});counts['pairs']+=1
            for world,axis in (('critical_edit','critical_fact'),('missing_evidence','missing_document')):
                for view in VIEWS:
                    a,b=caseids[('clean',view)],caseids[(world,view)]
                    add('pairs',split,{'pair_id':ident(a+b),'family_id':family,'case_id_a':a,'case_id_b':b,'relation':'sensitivity','axis':axis,'edit_json':json.dumps(worlds[world][1],ensure_ascii=False,sort_keys=True)});counts['pairs']+=1
        print(json.dumps({'mechanism_complete':mechanism,'cases':counts['cases']}),flush=True)
    for key,writer in writers.items():
        if buffers[key]:writer.write_table(pa.Table.from_pylist(buffers[key],schema=CASE_SCHEMA if key[0]=='cases' else PAIR_SCHEMA),row_group_size=250)
        writer.close()
    for h in spec_handles.values():h.close()
    stats={'dataset_id':'Bayanat-Labs/arabic-reconciliation-bench','version':'0.1.0','seed':args.seed,'families':sum(family_counts.values()),'family_counts':dict(family_counts),'counts':dict(counts),'split_counts':{k:dict(v) for k,v in split_counts.items()},'mechanisms':list(MECHANISMS),'views':list(VIEWS),'mechanism_case_counts':dict(mechanism_counts),'evidence_field_count':{'min':min(evidence_counts),'max':max(evidence_counts),'mean':sum(evidence_counts)/len(evidence_counts)},'data_origin':'Original programmatically generated fictional business cases; Arabic/English controlled templates authored with AI assistance; no human expert validation.','code_sha256':{n:hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in ('core.py','generator.py')}}
    (root/'statistics.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2)+'\n');print(json.dumps(stats,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
