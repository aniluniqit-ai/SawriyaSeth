import json
from kotak_api import KotakNeoAPI
try:
    cfg = json.load(open("config/config.json"))["kotak"]
    api = KotakNeoAPI(cfg)
    if api.login():
        print("Logged in!")
        sym = api.get_active_mcx_symbol("CRUDEOIL")
        print("CRUDEOIL Active Symbol:", sym)
        print("CRUDEOIL LTP:", api.get_ltp(sym, "mcx_fo"))
        
        sym2 = api.get_active_mcx_symbol("NATURALGAS")
        print("NATURALGAS Active Symbol:", sym2)
        print("NATURALGAS LTP:", api.get_ltp(sym2, "mcx_fo"))
    else:
        print("Failed to login.")
except Exception as e:
    print("Error:", e)
