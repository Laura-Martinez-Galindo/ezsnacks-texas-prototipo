"""QuickBooks simulado para las pruebas: calcula el impuesto recibo por recibo como QuickBooks."""
from ezsnack import cierre as cie
class Falso:
    renovado=False
    def __init__(s): s.rates={}; s.codes={}; s.n=100; s.recibos={}; s.items={}; s.cuentas={}; s.otros={}
    def _id(s): s.n+=1; return str(s.n)
    def query(s,sql):
        e=sql.split()[3]
        if e=="TaxRate": return [{"Id":i,"Name":n,"RateValue":v} for n,(i,v) in s.rates.items()]
        if e=="TaxCode": return [{"Id":i,"Name":n,"SalesTaxRateList":{"TaxRateDetail":[{"TaxRateRef":{"value":x}} for x in rs]}} for n,(i,rs) in s.codes.items()]
        if e=="TaxAgency": return [{"Id":"1","DisplayName":"Texas State Comptroller"}]
        if e=="SalesReceipt": return list(s.recibos.values())
        if e=="Item":
            if "where" not in sql.lower(): return list(s.items.values())
            if "NonInventory" in sql: return [it for it in s.items.values() if it["Type"]=="NonInventory"]
            nombre=sql.split("'")[-2]
            return [it for it in s.items.values() if it["Name"]==nombre and ("Active = false" not in sql)]
        if e in ("Account","Customer"):
            nombre=sql.split("'")[-2]; x=s.otros.get((e,nombre)); return [x] if x and "Active = false" not in sql else []
        return []
    def crear(s,e,c):
        x={**c,"Id":s._id(),"SyncToken":"0"}
        if e=="Item": s.items[x["Id"]]=x
        else: s.otros[(e,c.get("Name") or c.get("DisplayName"))]=x
        return x
    def actualizar(s,e,c):
        if e=="Item": s.items[c["Id"]].update({k:v for k,v in c.items() if k!="sparse"}); return s.items[c["Id"]]
        return c
    def _peticion(s,m,ruta,json_body=None,**k):
        if ruta=="taxservice/taxcode":
            ids=[]
            for d in json_body["TaxRateDetails"]:
                if "TaxRateId" in d: ids.append(d["TaxRateId"])
                else: i=s._id(); s.rates[d["TaxRateName"]]=(i,d["RateValue"]); ids.append(i)
            i=s._id(); s.codes[json_body["TaxCode"]]=(i,ids); return {"TaxCodeId":i}
        if ruta=="batch":
            out=[]
            byid={i:(n,v) for n,(i,v) in s.rates.items()}; code={i:rs for n,(i,rs) in s.codes.items()}
            for it in json_body["BatchItemRequest"]:
                if "Item" in it:
                    c=it["Item"]
                    if it["operation"]=="create":
                        if any(x["Name"].lower()==c["Name"].lower() for x in s.items.values()):
                            out.append({"bId":it["bId"],"Fault":{"Error":[{"Message":"Duplicate Name"}]}}); continue
                        x=s.crear("Item",c)
                    else: x=s.actualizar("Item",c)
                    out.append({"bId":it["bId"],"Item":x}); continue
                rc=it["SalesReceipt"]
                for l in rc["Line"]:
                    iid=l["SalesItemLineDetail"]["ItemRef"]["value"]
                    assert iid in s.items or iid.isdigit(), iid
                base=sum(l["Amount"] for l in rc["Line"] if l["SalesItemLineDetail"]["TaxCodeRef"]["value"]=="TAX")
                lines=[]; tot=0
                for rid in code[rc["TxnTaxDetail"]["TxnTaxCodeRef"]["value"]]:
                    amt=cie._c(base*byid[rid][1]/100); tot+=amt
                    lines.append({"Amount":amt,"TaxLineDetail":{"TaxRateRef":{"value":rid},"TaxPercent":byid[rid][1],"NetAmountTaxable":base}})
                rc={**rc,"Id":rc.get("Id") or s._id(),"SyncToken":"0","TotalAmt":sum(l["Amount"] for l in rc["Line"])+tot,"TxnTaxDetail":{"TotalTax":tot,"TaxLine":lines}}
                s.recibos[rc["DocNumber"]]=rc; out.append({"bId":it["bId"],"SalesReceipt":rc})
            return {"BatchItemResponse":out}
