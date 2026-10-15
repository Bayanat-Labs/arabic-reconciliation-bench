"""Visible-input rendering and exact scoped procurement reference (Apache-2.0)."""
from __future__ import annotations
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
import json

ROLES = ('policy','po','invoice','receipts','returns','history','amendments')
TITLES = {
 'policy':('سياسة المطابقة الخاصة بهذه الحالة','Case-specific matching policy'),
 'po':('أمر الشراء','Purchase order'), 'invoice':('فاتورة المورد','Supplier invoice'),
 'receipts':('سجل استلام البضائع','Goods receipt register'),
 'returns':('سجل المرتجعات','Returns register'),
 'history':('سجل الفواتير السابقة','Prior invoice register'),
 'amendments':('سجل تعديلات الأسعار','Price amendment register')}
LABELS = {
 'price_tolerance_bps':('التفاوت المسموح في سعر الوحدة','Allowed unit-price variance'),
 'receipt_cutoff':('آخر تاريخ يُحتسب للاستلام','Receipt cutoff'),
 'required_roles':('المستندات الواجب توافرها','Required documents'),
 'accepted_only':('استبعاد الكميات المرفوضة والمرتجعات المعتمدة','Exclude rejected quantities and approved returns'),
 'cumulative_billing':('خصم كميات الفواتير السابقة المرحلة','Deduct previously posted invoice quantities'),
 'approved_amendments_only':('اعتماد آخر تعديل معتمد ونافذ بتاريخ الفاتورة','Use latest approved amendment effective on invoice date'),
 'canceled_orders_forbidden':('منع مطابقة أوامر الشراء الملغاة','Canceled purchase orders cannot match'),
 'order_id':('رقم أمر الشراء','Purchase order ID'), 'status':('الحالة','Status'),
 'currency':('العملة','Currency'), 'sku':('رمز الصنف','Item code'),
 'ordered_units':('الكمية المطلوبة بالقطعة','Ordered base units'),
 'units_per_pack':('عدد القطع في العبوة','Base units per pack'),
 'unit_price_minor':('سعر الوحدة النقدية','Unit price in currency units'),
 'discount_bps':('خصم البند','Line discount'), 'invoice_id':('رقم الفاتورة','Invoice ID'),
 'date':('التاريخ الميلادي','Gregorian date'), 'stated_net_minor':('الإجمالي الصافي المدوّن','Stated net total'),
 'quantity_units':('الكمية بالقطعة','Quantity in base units'),
 'complete':('السجل كامل للفترة حتى تاريخ الفاتورة','Register is complete through invoice date'),
 'receipt_id':('رقم محضر الاستلام','Receipt ID'), 'quantity':('الكمية المستلمة','Delivered quantity'),
 'quantity_unit':('وحدة الاستلام','Receipt quantity unit'),
 'rejected_quantity':('الكمية المرفوضة بوحدة الاستلام نفسها','Rejected quantity in the same receipt unit'),
 'return_id':('رقم المرتجع','Return ID'), 'amendment_id':('رقم التعديل','Amendment ID'),
 'effective_date':('تاريخ بدء النفاذ','Effective date')}
AR_ENUM = {'true':'نعم','active':'ساري المفعول','canceled':'ملغى','approved':'معتمد',
 'draft':'مسودة','posted':'مرحّل','void':'ملغى','unit':'قطعة','pack':'عبوة',
 'invoice_date':'تاريخ الفاتورة شاملاً ذلك اليوم'}
EN_ENUM = {'true':'yes','invoice_date':'invoice date, inclusive'}
POLICY_AR = (
 'هذه سياسة افتراضية لهذه الحالة فقط. لا تمثل قاعدة محاسبية أو ضريبية عامة. '
 'تُطابق الفاتورة بأمر الشراء وسجلات الاستلام والمرتجعات والفواتير السابقة والتعديلات. '
 'يلزم وجود المستندات المطلوبة كلها؛ عند غياب أحدها تكون النتيجة insufficient_evidence. '
 'لا تُحتسب الاستلامات المؤرخة بعد تاريخ الفاتورة. تُطرح الكميات المرفوضة والمرتجعات المعتمدة '
 'حتى تاريخ الفاتورة، ثم كميات الفواتير السابقة المرحلة لهذا الأمر. تُحوّل العبوات إلى قطع '
 'وفق تعريف العبوة في أمر الشراء. لا يجوز أن تتجاوز كمية الفاتورة الرصيد المستلم أو رصيد الأمر. '
 'رقم فاتورة موجود في سجل الفواتير المرحلة يعني تكرار الفاتورة. '
 'آخر تعديل سعر معتمد يبدأ نفاذه في تاريخ الفاتورة أو قبله يحل محل سعر أمر الشراء؛ '
 'المسودات والتعديلات المستقبلية لا تُطبق. يُقارن السعر الفعلي بالسعر التعاقدي ضمن نسبة التفاوت المبينة، '
 'ويجب أن يتطابق الخصم والعملة. لا يوجد تحويل عملة. يُحسب الإجمالي المدوّن من أسعار الفاتورة '
 'وخصوماتها. جميع القيم صافية، دون ضرائب أو رسوم، والتقريب لكل بند إلى أقرب جزء من مئة بنصف إلى أعلى.')
POLICY_EN = (
 'This fictional policy applies only to this case; it is not a general accounting or tax rule. '
 'All required documents must be present, otherwise return insufficient_evidence. '
 'Count receipts dated on or before the invoice date. Subtract rejected quantities, approved returns '
 'through that date, and prior posted invoice quantities for this order. Convert receipt packs using '
 'the purchase order pack size. Invoice quantities must not exceed either remaining ordered units or '
 'net received units. An invoice ID already in posted history is a duplicate. The latest approved '
 'price amendment effective on or before invoice date replaces the PO price; ignore draft and future '
 'amendments. Unit prices must be within the stated tolerance; line discounts and currency must '
 'match. No FX conversion. Check the stated total using invoice prices and discounts. All amounts '
 'are net of tax and fees. Round each line half-up to the nearest minor unit.')
QUESTION_AR = ('افحص مطابقة الفاتورة وفق السياسة والمستندات المتاحة. احسب القيمة الصافية التعاقدية '
 'لكميات الفاتورة باستخدام أسعار العقد النافذة وخصومات أمر الشراء، لا باستخدام الحد الأدنى من '
 'الكميات المستلمة. القيمة التعاقدية ليست مبلغاً معتمداً للدفع. أعد decision وcontract_net_minor '
 'وissues وevidence_ids فقط بصيغة JSON. الجزء النقدي الأصغر يساوي 1/100 من وحدة العملة. '
 'يمكن معرفة القيمة التعاقدية مع نقص سجل الاستلام مثلاً؛ أعد null إذا غاب أمر الشراء أو '
 'الفاتورة أو سجل التعديلات. الاستشهادات هي معرّفات الحقول بين الأقواس المربعة.')
QUESTION_EN = ('Reconcile the invoice under the supplied policy and evidence. Calculate the nominal '
 'contract net for the invoiced quantities using effective contractual prices and PO discounts, '
 'not the minimum received quantity. This is not an approved payable amount. Return only JSON '
 'with decision, contract_net_minor, issues, evidence_ids. A minor unit is 1/100 currency unit. '
 'The contract net can remain known when receipt evidence is missing; return null if PO, invoice '
 'or amendment register is absent. Cite visible bracketed field IDs.')
OUTPUT_CONTRACT = ('Return exactly one JSON object. decision: match, mismatch, or insufficient_evidence. '
 'contract_net_minor: integer or null. issues: array of zero or more codes from order_canceled, '
 'currency_mismatch, duplicate_invoice, quantity_shortfall, price_mismatch, discount_mismatch, '
 'invoice_arithmetic, missing_evidence. evidence_ids: array of visible field IDs actually used. '
 'No code fences or additional prose. Never use outside rules or assume missing evidence.')

def rounded_net(quantity, price, discount):
    return int((Decimal(quantity)*Decimal(price)*Decimal(10000-discount)/Decimal(10000)).quantize(Decimal('1'),rounding=ROUND_HALF_UP))

class Facts:
    def __init__(self,documents):
        self.docs={d['role']:d for d in documents};self.evidence=set()
    def header(self,role): return {f['key']:f for f in self.docs[role]['fields'] if not f['row_id']}
    def rows(self,role):
        groups=defaultdict(dict)
        for f in self.docs[role]['fields']:
            if f['row_id']:groups[f['row_id']][f['key']]=f
        return list(groups.values())
    def get(self,row,key,integer=False):
        f=row[key];self.evidence.add(f['id']);return int(f['value']) if integer else f['value']

def compute_gold(documents):
    f=Facts(documents);g=f.get;trace={'lines':[]};issues=set()
    if 'policy' in f.docs:
        policy=f.header('policy')
        for key in policy:g(policy,key)
    total=None;po_rows={};inv_rows=[];effective={}
    if all(role in f.docs for role in ('po','invoice','amendments')):
        ih=f.header('invoice');invoice_date=g(ih,'date')
        for row in f.rows('po'):po_rows[g(row,'sku')]=row
        inv_rows=f.rows('invoice')
        g(f.header('amendments'),'complete')
        amendments=[]
        for row in f.rows('amendments'):
            sku,status,date=g(row,'sku'),g(row,'status'),g(row,'effective_date')
            if status=='approved' and date<=invoice_date:amendments.append((sku,date,row))
        total=0
        for row in inv_rows:
            sku,q=g(row,'sku'),g(row,'quantity_units',True);pr=po_rows[sku]
            price,discount=g(pr,'unit_price_minor',True),g(pr,'discount_bps',True)
            candidates=[a for a in amendments if a[0]==sku]
            if candidates:price=g(max(candidates,key=lambda x:x[1])[2],'unit_price_minor',True)
            effective[sku]=price
            amount=rounded_net(q,price,discount);total+=amount
            trace['lines'].append({'sku':sku,'quantity_units':q,'effective_unit_price_minor':price,'contract_discount_bps':discount,'contract_net_minor':amount})
    missing=[role for role in ROLES if role not in f.docs]
    if missing:
        return {'decision':'insufficient_evidence','contract_net_minor':total,'issues':['missing_evidence'],
                'evidence_ids':sorted(f.evidence),'trace':dict(trace,missing_roles=missing)}
    ph,ih=f.header('po'),f.header('invoice')
    order=g(ph,'order_id');status=g(ph,'status');currency=g(ph,'currency')
    inv_id,inv_order,inv_date,inv_currency,stated=[g(ih,k,k=='stated_net_minor') for k in ('invoice_id','order_id','date','currency','stated_net_minor')]
    if inv_order!=order:raise ValueError('Order identity outside this version scope')
    if status=='canceled':issues.add('order_canceled')
    if currency!=inv_currency:issues.add('currency_mismatch')
    tolerance=g(policy,'price_tolerance_bps',True)
    receipt_rows=[];return_rows=[];history_rows=[]
    for role in ('receipts','returns','history'):g(f.header(role),'complete')
    for row in f.rows('receipts'):
        sku,date=g(row,'sku'),g(row,'date');receipt_rows.append((sku,date,row))
    for row in f.rows('returns'):
        sku,date,status=g(row,'sku'),g(row,'date'),g(row,'status');return_rows.append((sku,date,status,row))
    for row in f.rows('history'):
        h_order,status,h_id=g(row,'order_id'),g(row,'status'),g(row,'invoice_id')
        if status=='posted' and h_id==inv_id:issues.add('duplicate_invoice')
        if h_order==order and status=='posted':
            sku,q=g(row,'sku'),g(row,'quantity_units',True);history_rows.append((sku,q))
    invoice_sum=0
    for row,line in zip(inv_rows,trace['lines']):
        sku,q=g(row,'sku'),g(row,'quantity_units',True);pr=po_rows[sku]
        price,discount=g(row,'unit_price_minor',True),g(row,'discount_bps',True)
        ordered=g(pr,'ordered_units',True);contract_discount=g(pr,'discount_bps',True)
        if abs(price-effective[sku])*10000>effective[sku]*tolerance:issues.add('price_mismatch')
        if discount!=contract_discount:issues.add('discount_mismatch')
        received=0
        for rs,dt,rr in receipt_rows:
            if rs!=sku or dt>inv_date:continue
            quantity,unit,rejected=g(rr,'quantity',True),g(rr,'quantity_unit'),g(rr,'rejected_quantity',True)
            multiplier=g(pr,'units_per_pack',True) if unit=='pack' else 1
            received+=(quantity-rejected)*multiplier
        returned=sum(g(rr,'quantity_units',True) for rs,dt,status,rr in return_rows if rs==sku and dt<=inv_date and status=='approved')
        previous=sum(n for rs,n in history_rows if rs==sku)
        if q>ordered-previous or q>received-returned-previous:issues.add('quantity_shortfall')
        invoice_sum+=rounded_net(q,price,discount)
        line.update(received_units=received,returned_units=returned,previously_billed_units=previous,remaining_received_units=received-returned-previous,remaining_ordered_units=ordered-previous)
    if invoice_sum!=stated:issues.add('invoice_arithmetic')
    trace.update(invoice_net_minor=invoice_sum,stated_net_minor=stated)
    return {'decision':'mismatch' if issues else 'match','contract_net_minor':total,
            'issues':sorted(issues),'evidence_ids':sorted(f.evidence),'trace':trace}

def field_display(field,language='ar',eastern=False):
    key,value=field['key'],str(field['value'])
    if key.endswith('_minor'):value=f'{int(value)//100}.{int(value)%100:02d}'
    elif key.endswith('_bps'):value=f'{int(value)//100}.{int(value)%100:02d}%'
    elif key=='required_roles':value='، '.join(TITLES[x][0] for x in value.split(',')) if language=='ar' else ', '.join(TITLES[x][1] for x in value.split(','))
    else:value=(AR_ENUM if language=='ar' else EN_ENUM).get(value,value)
    # Opaque identifiers and references stay ASCII across numeral views.
    if eastern and not key.endswith('_id') and key!='sku':value=value.translate(str.maketrans('0123456789.,','٠١٢٣٤٥٦٧٨٩٫٬'))
    return value

def render_documents(documents,view,style):
    language='en' if view=='en_control' else 'ar';reverse=view=='ar_reordered'
    result=[]
    for doc in reversed(documents) if reverse else documents:
        lines=[]
        if doc['role']=='policy':lines.append(POLICY_EN if language=='en' else POLICY_AR)
        groups=defaultdict(list)
        for field in doc['fields']:groups[field['row_id']].append(field)
        keys=list(groups)
        if reverse:keys.reverse()
        for group in keys:
            if group:lines.append(('Record ' if language=='en' else 'السجل ')+group)
            fields=list(reversed(groups[group])) if reverse else groups[group]
            for field in fields:
                ar,en=LABELS[field['key']]
                label=en if language=='en' else ar
                if language=='ar' and style==1:
                    label={'الحالة':'حالة القيد','التاريخ الميلادي':'تاريخ المستند بالميلادي','الكمية بالقطعة':'كمية القطع','رقم الفاتورة':'معرّف الفاتورة','رقم أمر الشراء':'معرّف أمر الشراء'}.get(label,label)
                if language=='ar' and style==2:
                    label={'الحالة':'حالة المستند','التاريخ الميلادي':'تاريخ القيد الميلادي','الكمية بالقطعة':'عدد القطع','سعر الوحدة النقدية':'السعر لكل قطعة نقداً','رقم أمر الشراء':'مرجع أمر التوريد'}.get(label,label)
                if language=='ar' and style==3:
                    label={'الحالة':'وضع المستند','العملة':'عملة المستند','الكمية بالقطعة':'العدد بوحدة القطعة','الإجمالي الصافي المدوّن':'صافي الفاتورة المثبت','خصم البند':'نسبة الخصم للبند'}.get(label,label)
                lines.append(f"[{field['id']}] {label}: {field_display(field,language,view=='ar_eastern')}")
        result.append({'doc_id':doc['doc_id'],'title':TITLES[doc['role']][language=='en'],'text':'\n'.join(lines)})
    return result

def model_input(row):
    parts=[OUTPUT_CONTRACT,row['question']]
    for doc in row['documents']:parts.append(f"\n--- {doc['doc_id']} | {doc['title']} ---\n{doc['text']}")
    return '\n\n'.join(parts)
